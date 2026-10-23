"""Builds the downloadable client report as a real PDF.

Written for a homeowner or small builder, not an engineer: plain sentences, the
two scores side by side, what to change, and the clause behind each change.

Deliberately **deterministic** — no language model is involved. Every sentence is
assembled from figures the engine computed. In a document a client may take to a
contractor, a fabricated number would be the worst possible failure, and the
surest way to prevent one is to leave no room for invention.

The chart is drawn directly with ReportLab primitives rather than rasterised from
the frontend, so the PDF needs no browser and stays vector-sharp when printed.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from urllib.parse import urlencode

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

from app.core.logging import get_logger
from app.services.rules_engine import ComplianceFinding
from app.services.scoring import ScoreComparison, ScoredSelection

# The public server that hosts the live audit result.
_LIVE_BASE_URL = "http://13.203.248.62"
# Edge length of the QR code printed in the PDF corner.
_QR_SIZE_MM = 28 * mm

logger = get_logger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 20 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

# Matched to the on-screen palette so the printed report and the app read as one
# product: cement greys, indigo for headings, one reserved accent for the gain.
INK = colors.HexColor("#2E3440")
INDIGO = colors.HexColor("#3B4A7A")
GREY = colors.HexColor("#6B7280")
LIGHT = colors.HexColor("#E5E7EB")
SIGNAL = colors.HexColor("#C8862B")

BAND_COLOURS = {
    "poor": colors.HexColor("#B4472F"),
    "marginal": colors.HexColor("#C87A38"),
    "adequate": colors.HexColor("#B99334"),
    "good": colors.HexColor("#4C8055"),
    "excellent": colors.HexColor("#3B7368"),
}

BAND_SENTENCE = {
    "poor": "falls well short of the code for this site",
    "marginal": "is below the code minimum in places",
    "adequate": "meets the code, with little margin",
    "good": "clears the code comfortably",
    "excellent": "is well ahead of the code minimum",
}

PARAMETER_LABELS = {
    "concrete_grade_mpa": "Concrete grade",
    "cement_content_kg_m3": "Cement content (kg/m3)",
    "water_cement_ratio": "Water/cement ratio",
    "walling_climate_suitability": "Walling material",
}


class _Cursor:
    """Tracks the vertical position and starts a new page when space runs out."""

    def __init__(self, canvas: pdf_canvas.Canvas) -> None:
        self.canvas = canvas
        self.y = PAGE_HEIGHT - MARGIN

    def space(self, amount: float) -> None:
        """Move down, breaking the page if the block would not fit."""
        if self.y - amount < MARGIN:
            self.canvas.showPage()
            self.y = PAGE_HEIGHT - MARGIN
        self.y -= amount

    def text(
        self, value: str, size: float = 10, colour: colors.Color = INK, bold: bool = False
    ) -> None:
        """Draw one line of body text."""
        self.space(size + 4)
        self.canvas.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        self.canvas.setFillColor(colour)
        self.canvas.drawString(MARGIN, self.y, value)

    def paragraph(self, value: str, size: float = 10) -> None:
        """Draw wrapped body text.

        Wrapped by measured width rather than character count, so the right edge
        stays even whatever the content.
        """
        words = value.split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if self.canvas.stringWidth(candidate, "Helvetica", size) > CONTENT_WIDTH:
                self.text(line, size)
                line = word
            else:
                line = candidate
        if line:
            self.text(line, size)

    def heading(self, value: str) -> None:
        """Draw a section heading with its rule."""
        self.space(16)
        self.canvas.setFont("Helvetica-Bold", 12)
        self.canvas.setFillColor(INDIGO)
        self.canvas.drawString(MARGIN, self.y, value)
        self.space(4)
        self.canvas.setStrokeColor(LIGHT)
        self.canvas.setLineWidth(0.75)
        self.canvas.line(MARGIN, self.y, PAGE_WIDTH - MARGIN, self.y)


def _draw_comparison(cursor: _Cursor, comparison: ScoreComparison, evaluated_own: bool) -> None:
    """Draw the before/after columns — the report's one visual.

    Same construction as the screen: two columns from a shared baseline so the gap
    is a height rather than a subtraction the reader performs.
    """
    chart_height = 45 * mm
    cursor.space(chart_height + 22 * mm)
    canvas = cursor.canvas
    baseline = cursor.y + 14 * mm

    column_width = 26 * mm
    gap = 34 * mm
    left_x = MARGIN + 18 * mm
    right_x = left_x + column_width + gap

    for x, scored, caption in (
        (left_x, comparison.proposed, "Your specification" if evaluated_own else "Typical build"),
        (right_x, comparison.recommended, "What we'd specify"),
    ):
        height = max(scored.score / 100 * chart_height, 1.0)

        canvas.setFillColor(LIGHT)
        canvas.rect(x, baseline, column_width, chart_height, stroke=0, fill=1)
        canvas.setFillColor(BAND_COLOURS.get(scored.band, GREY))
        canvas.rect(x, baseline, column_width, height, stroke=0, fill=1)

        canvas.setFont("Helvetica-Bold", 20)
        canvas.drawCentredString(x + column_width / 2, baseline - 9 * mm, f"{scored.score:.0f}")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GREY)
        canvas.drawCentredString(x + column_width / 2, baseline - 13 * mm, caption)

    # The gain, in the one colour reserved for it.
    canvas.setFillColor(SIGNAL)
    canvas.setFont("Helvetica-Bold", 15)
    midpoint = left_x + column_width + gap / 2
    canvas.drawCentredString(
        midpoint, baseline + chart_height / 2, f"+{comparison.improvement:.0f}"
    )
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(midpoint, baseline + chart_height / 2 - 5 * mm, "points")


def _finding_row(cursor: _Cursor, finding: ComplianceFinding) -> None:
    """Draw one compliance row."""
    canvas = cursor.canvas
    cursor.space(13)
    label = PARAMETER_LABELS.get(finding.parameter, finding.parameter)

    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(INK)
    canvas.drawString(MARGIN, cursor.y, label)
    canvas.drawRightString(MARGIN + CONTENT_WIDTH * 0.62, cursor.y, f"{finding.required:g}")
    canvas.drawRightString(MARGIN + CONTENT_WIDTH * 0.80, cursor.y, f"{finding.provided:g}")

    canvas.setFillColor(BAND_COLOURS["good"] if finding.compliant else BAND_COLOURS["poor"])
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawRightString(
        MARGIN + CONTENT_WIDTH, cursor.y, "Meets" if finding.compliant else "Short"
    )


def _spec_lines(scored: ScoredSelection) -> list[str]:
    """The specification, written out as a builder would read it."""
    mix = scored.selection.concrete
    lines = [
        f"Concrete: {mix.grade}, {mix.cement_content_kg_m3:.0f} kg/m3 cement, "
        f"water/cement {mix.water_cement_ratio:.2f}",
        f"Cement type: {mix.cement_type}",
        f"Walling: {scored.selection.walling_material_id.replace('_', ' ')}",
    ]
    if mix.admixtures:
        lines.append(f"Admixtures: {', '.join(mix.admixtures)}")
    return lines


def build_report_pdf(comparison: ScoreComparison, *, evaluated_own_materials: bool) -> bytes:
    """Render the client report.

    Args:
        comparison: The scored before/after from the engine.
        evaluated_own_materials: Whether the user supplied a specification, which
            changes only how the left-hand column is described.

    Returns:
        The PDF as bytes, ready to stream to the browser.
    """
    buffer = io.BytesIO()
    canvas = pdf_canvas.Canvas(buffer, pagesize=A4)
    canvas.setTitle(f"Building Quality Score - {comparison.district}")
    cursor = _Cursor(canvas)

    # --- Header -----------------------------------------------------------
    cursor.text("Building Quality Score", 17, INDIGO, bold=True)
    cursor.text(
        f"{comparison.district} district  ·  {comparison.exposure.label} exposure", 10, GREY
    )
    cursor.text(f"Prepared {datetime.now(UTC).strftime('%d %B %Y')}", 8, GREY)

    # --- Summary ----------------------------------------------------------
    cursor.heading("What we found")
    verdict = BAND_SENTENCE.get(comparison.proposed.band, "was assessed")
    subject = "Your specification" if evaluated_own_materials else "A typical local specification"
    cursor.paragraph(
        f"{subject} scores {comparison.proposed.score:.0f} out of 100 for building in "
        f"{comparison.district}. It {verdict}. Following the specification in this report "
        f"would raise that to {comparison.recommended.score:.0f}, a gain of "
        f"{comparison.improvement:.0f} points."
    )

    _draw_comparison(cursor, comparison, evaluated_own_materials)

    # --- Why --------------------------------------------------------------
    cursor.heading("Why your site is rated this way")
    for reason in comparison.exposure_reasons:
        cursor.paragraph(f"- {reason}", 9)
    cursor.space(3)
    cursor.paragraph(
        f"Measured from {comparison.provenance['observation_start']} to "
        f"{comparison.provenance['observation_end']} using {comparison.provenance['dataset']}.",
        8,
    )

    # --- Compliance -------------------------------------------------------
    cursor.heading("How your materials measure up")
    canvas.setFont("Helvetica-Bold", 8)
    cursor.space(12)
    canvas.setFillColor(GREY)
    canvas.drawString(MARGIN, cursor.y, "REQUIREMENT")
    canvas.drawRightString(MARGIN + CONTENT_WIDTH * 0.62, cursor.y, "CODE NEEDS")
    canvas.drawRightString(MARGIN + CONTENT_WIDTH * 0.80, cursor.y, "YOU HAVE")
    canvas.drawRightString(MARGIN + CONTENT_WIDTH, cursor.y, "RESULT")
    for finding in comparison.proposed.assessment.findings:
        _finding_row(cursor, finding)

    # --- What to build ----------------------------------------------------
    cursor.heading("What to build with")
    for line in _spec_lines(comparison.recommended):
        cursor.paragraph(f"- {line}", 9)

    applicable = comparison.proposed.assessment.applicable_recommendations
    followed = set(comparison.proposed.assessment.followed_recommendation_ids)
    if applicable:
        cursor.space(4)
        cursor.text("Because of this district's climate:", 9, INK, bold=True)
        for recommendation in applicable:
            suffix = " (already in your plan)" if recommendation.id in followed else ""
            cursor.paragraph(
                f"- {recommendation.material} — {recommendation.purpose}. "
                f"{recommendation.standard}.{suffix}",
                9,
            )

    # --- Limits -----------------------------------------------------------
    cursor.heading("What this report does not tell you")
    cursor.paragraph(
        "This score measures how well a specification complies with IS 456 for the climate "
        "measured at your district, on a 0-100 scale of our own definition. It is not a "
        "prediction that a building will or will not fail, it is not a structural design, and "
        "it is not a survey of any actual building. It does not account for drainage, ground "
        "conditions, workmanship or maintenance. Have a qualified structural engineer confirm "
        "any specification before you build.",
        9,
    )
    cursor.space(4)
    cursor.paragraph(f"Score model: {comparison.model_version}.", 8)

    # --- Verification QR code -----------------------------------------------
    # Placed in the bottom-right corner so it never overlaps body text.
    _draw_verification_qr(canvas, comparison)

    canvas.showPage()
    canvas.save()

    payload = buffer.getvalue()
    logger.info("report_pdf_built", district=comparison.district, bytes=len(payload))
    return payload


def _build_verify_url(comparison: ScoreComparison) -> str:
    """Return the deep-link URL that the QR code should resolve to.

    Opens the live app with the district pre-selected so the officer lands
    directly on the audit result without any manual navigation.
    """
    params = urlencode(
        {
            "district": comparison.district,
            "score": f"{comparison.proposed.score:.0f}",
            "band": comparison.proposed.band,
        }
    )
    return f"{_LIVE_BASE_URL}/?{params}"


def _draw_verification_qr(canvas: pdf_canvas.Canvas, comparison: ScoreComparison) -> None:
    """Render the QR code into the bottom-right corner of the current page.

    Soft-fails: if the ``qrcode`` library is unavailable or the image cannot be
    built, we log a warning and leave the PDF intact rather than crashing.
    """
    try:
        url = _build_verify_url(comparison)
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Write the PIL image to a bytes buffer so ReportLab can read it.
        img_buf = io.BytesIO()
        img.save(img_buf, format="PNG")
        img_buf.seek(0)

        x = PAGE_WIDTH - MARGIN - _QR_SIZE_MM
        y = MARGIN

        from reportlab.lib.utils import ImageReader  # local import to keep top-level tidy

        canvas.drawImage(
            ImageReader(img_buf),
            x,
            y,
            width=_QR_SIZE_MM,
            height=_QR_SIZE_MM,
            preserveAspectRatio=True,
            mask="auto",
        )

        # Caption under the QR code.
        canvas.setFont("Helvetica", 5.5)
        canvas.setFillColor(GREY)
        canvas.drawCentredString(
            x + _QR_SIZE_MM / 2,
            y - 4 * mm,
            "Scan to verify online",
        )
    except Exception:
        logger.warning("report_pdf_qr_failed", district=comparison.district)
