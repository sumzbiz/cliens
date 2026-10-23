/**
 * Step 5 — the result.
 *
 * The score is fetched here, on mount, from the session's specification. It is
 * deliberately not cached in the session: coming back to this page after editing an
 * input must re-score, never show a stale number beside changed inputs.
 */
import { motion, useReducedMotion } from 'motion/react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { PageShell } from '@/components/Shell';
import { VoiceExplainer } from '@/components/VoiceExplainer';
import { scoreNarration } from '@/lib/narration.ta';
import { useVoice } from '@/state/voice-context';
import { ScoreComparison } from '@/components/ScoreComparison';
import { ServiceLifeComparison } from '@/components/ServiceLifeComparison';
import { Button, ErrorNotice, Panel, Popup, Spinner } from '@/components/ui';
import { useAction } from '@/hooks/useAction';
import { apiClient } from '@/lib/api-client';
import { formatParameter, formatPercent } from '@/lib/format';
import { boundsOf } from '@/lib/geo';
import { useSession, type SiteSpecification } from '@/state/session-context';
import type { MaterialSelectionInput, ScoreResponse } from '@/types/api';
import { useLanguage } from '@/state/language-context';

const EXPOSURE_TA: Record<string, string> = {
  Mild: 'குறைந்த', Moderate: 'மிதமான', Severe: 'கடுமையான', 'Very severe': 'மிகக் கடுமையான', VerySevere: 'மிகக் கடுமையான', Extreme: 'அதீத',
};
const FINDING_LABEL_TA: Record<string, string> = {
  concrete_grade_mpa: 'கான்கிரீட் தரம்',
  cement_content_kg_m3: 'சிமெண்டு அளவு',
  water_cement_ratio: 'நீர்/சிமெண்டு விகிதம்',
  walling_climate_suitability: 'சுவர் பொருளின் காலநிலைப் பொருத்தம்',
};

/**
 * The materials payload, or null.
 *
 * Null is meaningful to the API: it means "recommend rather than evaluate". Derived
 * in one place so the score request and the report request cannot disagree.
 */
function materialsPayload(spec: SiteSpecification): MaterialSelectionInput | null {
  return spec.evaluateOwnMaterials
    ? {
        concrete: spec.concrete,
        walling_material_id: spec.wallingMaterialId,
        element_situation: spec.situation,
      }
    : null;
}

export default function ScorePage() {
  const { spec, area } = useSession();
  const navigate = useNavigate();
  const reduced = useReducedMotion();
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [climateOpen, setClimateOpen] = useState(false);
  const voice = useVoice();
  const { t, language } = useLanguage();

  // Two report endpoints for the same reason there are two score endpoints: a
  // drawn outline has no district name, and the district report requires one.
  const report = useAction(
    async (): Promise<Blob> => {
      const outlineBounds = area === null ? null : boundsOf(area);
      return outlineBounds !== null
        ? apiClient.downloadAreaReport(outlineBounds, materialsPayload(spec), spec.situation)
        : apiClient.downloadReport(spec.district, materialsPayload(spec), spec.situation);
    }
  );

  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setError(null);
    // A drawn outline and a named district are different endpoints, because only
    // the area one can report whether its climate was interpolated.
    //
    // The climate lookup takes the outline's bounding box rather than the outline
    // itself. That is not a shortcut: the grid resolves to 27 km cells, so the
    // difference between a plot and the box around it is orders of magnitude
    // below what the data can distinguish. The *area* uses the real outline,
    // because there the difference is the entire point.
    const outlineBounds = area === null ? null : boundsOf(area);
    const pending =
      outlineBounds !== null
        ? apiClient.scoreArea(outlineBounds, materialsPayload(spec), spec.situation)
        : apiClient.score(spec.district, materialsPayload(spec), spec.situation);

    pending
      .then((response) => {
        if (!cancelled) {
          setResult(response);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [spec, area]);

  const handleDownload = useCallback(async () => {
    const blob = await report.run();
    if (blob === null) {
      return;
    }
    // Anchor-and-revoke: the browser needs a URL to save from, and the object URL
    // must be released or the blob stays in memory for the page's lifetime.
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    // Named from what was actually scored, since a drawn outline has no district.
    anchor.download = `building-quality-score-${(result?.district ?? 'site')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '')}.pdf`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [report, result]);

  return (
    <PageShell
      eyebrow="Step 5 of 5"
      // `result.district` rather than `spec.district`: a drawn outline has no
      // district name of its own, and the server names what it actually scored.
      title={result === null ? t('Scoring…') : language === 'ta' ? `${result.district} — மதிப்பீடு` : `${result.district}, scored`}
      lead={
        result === null
          ? undefined
          : language === 'ta'
            ? `நேரடியாக அளவிடப்பட்ட காலநிலைத் தரவின் அடிப்படையில் ${EXPOSURE_TA[result.exposure_label] ?? result.exposure_label} தாக்கம்.`
            : `${result.exposure_label} exposure, from climate measured on the ground rather than modelled.`
      }
      wide
    >
      {result === null && error === null && (
        <Panel className="p-10">
          <Spinner label={t('Checking your specification against IS 456…')} />
        </Panel>
      )}

      {error !== null && (
        <div className="space-y-5">
          <ErrorNotice error={error} />
          <Button
            variant="secondary"
            onClick={() => {
              void navigate('/materials');
            }}
          >
            {t('Go back and change something')}
          </Button>
        </div>
      )}

      {result !== null && (
        <div className="space-y-6">
          {/* Built from the live response, not a fixed script, so the spoken
              numbers can never drift from the ones on screen. */}
          <VoiceExplainer
            text={scoreNarration({
              district: result.district,
              exposureLabel: result.exposure_label,
              proposed: result.proposed.score,
              recommended: result.recommended.score,
              improvement: result.improvement,
              compliant: result.proposed.compliant,
            })}
            enabled={voice.enabled}
            label={language === 'ta' ? 'முடிவைக் கேளுங்கள்' : 'Hear the result'}
          />

          <ScoreComparison
            proposed={result.proposed}
            recommended={result.recommended}
            improvement={result.improvement}
            evaluatedOwnMaterials={spec.evaluateOwnMaterials}
          />

          <ServiceLifeComparison
            proposed={result.proposed}
            recommended={result.recommended}
            evaluatedOwnMaterials={spec.evaluateOwnMaterials}
          />

          <Panel className="p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="text-base font-semibold text-ink-1">
                {language === 'ta' ? `உங்கள் தளம் ${EXPOSURE_TA[result.exposure_label] ?? result.exposure_label} தாக்கத்தில் உள்ளது` : `Your site is ${result.exposure_label.toLowerCase()} exposure`}
              </h2>
              <button
                type="button"
                onClick={() => {
                  setClimateOpen(true);
                }}
                className="text-sm font-medium text-atmos underline underline-offset-4"
              >
                {t('See the measurements')}
              </button>
            </div>
            <ul className="mt-3 space-y-1.5 text-sm text-ink-2">
              {result.exposure_reasons.map((reason) => (
                <li key={reason} className="flex gap-2.5">
                  <span aria-hidden="true" className="text-ink-3">
                    —
                  </span>
                  {reason}
                </li>
              ))}
            </ul>
          </Panel>

          <Panel className="p-6">
            <h2 className="text-base font-semibold text-ink-1">{t('What we checked')}</h2>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[28rem] text-left text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-[11px] uppercase tracking-[0.12em] text-ink-3">
                    <th className="pb-2.5 font-medium">{t('Requirement')}</th>
                    <th className="pb-2.5 text-right font-medium">{t('Code needs')}</th>
                    <th className="pb-2.5 text-right font-medium">{t('You have')}</th>
                    <th className="pb-2.5 text-right font-medium">{t('Result')}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.proposed.findings.map((finding, index) => (
                    <motion.tr
                      key={finding.parameter}
                      className="border-b border-white/[0.06]"
                      initial={reduced === true ? false : { opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={
                        reduced === true ? { duration: 0 } : { delay: 0.05 * index, duration: 0.3 }
                      }
                    >
                      <td className="py-2.5 text-ink-1">
                        {language === 'ta' ? (FINDING_LABEL_TA[finding.parameter] ?? formatParameter(finding.parameter)) : formatParameter(finding.parameter)}
                        {!isSpecComparison(finding.parameter) && (
                          // This row is not a spec-versus-limit comparison, so the
                          // numeric columns are blank and the reason goes here
                          // instead — see `isSpecComparison`.
                          <span className="mt-0.5 block text-xs text-ink-3">
                            {finding.message}
                          </span>
                        )}
                      </td>
                      <td className="tabular py-2.5 text-right text-ink-2">
                        {isSpecComparison(finding.parameter)
                          ? formatFindingValue(finding.required)
                          : '—'}
                      </td>
                      <td className="tabular py-2.5 text-right text-ink-2">
                        {isSpecComparison(finding.parameter)
                          ? formatFindingValue(finding.provided)
                          : '—'}
                      </td>
                      <td
                        className={`py-2.5 text-right font-semibold ${
                          finding.compliant ? 'text-band-good' : 'text-band-poor'
                        }`}
                      >
                        {finding.compliant ? t('Meets') : t('Short')}
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {result.recommendations.length > 0 && (
            <Panel className="p-6">
              <h2 className="text-base font-semibold text-ink-1">
                {t('Recommended for this climate')}
              </h2>
              <ul className="mt-4 space-y-4">
                {result.recommendations.map((recommendation) => (
                  <li key={recommendation.id} className="text-sm">
                    <p className="font-semibold text-ink-1">
                      {recommendation.material}
                      {recommendation.followed && (
                        <span className="ml-2 text-xs font-medium text-band-good">
                          {t('already in your spec')}
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-ink-2">{recommendation.purpose}</p>
                    <p className="mt-0.5 text-xs text-ink-3">{recommendation.standard}</p>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          <Panel className="p-6">
            <h2 className="text-base font-semibold text-ink-1">{t('Take this with you')}</h2>
            <p className="mt-1 text-sm leading-relaxed text-ink-2">
              {t('A one-page summary you can hand to your contractor, with the specification and the code clause behind each item.')}
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              <Button
                onClick={() => {
                  void handleDownload();
                }}
                disabled={report.loading}
              >
                {report.loading ? t('Preparing…') : t('Download the report (PDF)')}
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  void navigate('/materials');
                }}
              >
                {t('Change my materials')}
              </Button>
            </div>
            {report.error !== null && (
              <div className="mt-4">
                <ErrorNotice error={report.error} />
              </div>
            )}
          </Panel>

          <p className="text-xs leading-relaxed text-ink-3">
            {language === 'ta'
              ? `${result.model_version} மாதிரி, IS 456 விதிமுறைப் பூர்த்தி அளவுகளின் அடிப்படையில் கணக்கிட்ட மதிப்பெண். இது அளவிடப்பட்ட காலநிலைக்கு எதிரான விதிமுறைப் பூர்த்தியை காட்டுகிறது; கட்டிடம் தோல்வியடையுமா என்ற கணிப்பு அல்ல.`
              : <>Score computed by {result.model_version}, from IS 456 compliance margins. It reflects code compliance against measured climate — it is not a prediction of whether a building will fail.</>}
          </p>

          <Popup
            open={climateOpen}
            title={language === 'ta' ? `${result.district} — அளவிடப்பட்ட காலநிலை` : `Measured climate for ${result.district}`}
            description={`${result.data_source['dataset'] ?? 'Reanalysis'}, ${String(result.climate.observation_days)} days observed.`}
            onClose={() => {
              setClimateOpen(false);
            }}
          >
            <dl className="grid grid-cols-2 gap-5">
              <Measurement
                label={t('Mean humidity')}
                value={`${result.climate.mean_relative_humidity_percent.toFixed(0)}%`}
              />
              <Measurement
                label={t('Mean peak temp')}
                value={`${result.climate.mean_max_temperature_c.toFixed(1)} °C`}
              />
              <Measurement
                label={t('Distance from coast')}
                value={`${result.climate.distance_to_coast_km.toFixed(0)} km`}
              />
              <Measurement
                label={t('Peak wind gust')}
                value={`${result.climate.max_wind_gust_ms.toFixed(1)} m/s`}
              />
              <Measurement
                label={t('Wet hours')}
                value={formatPercent(result.climate.wet_hours_fraction)}
              />
              <Measurement
                label={t('Wet/dry cycles')}
                value={`${result.climate.wet_dry_cycles_per_year.toFixed(0)} /yr`}
              />
            </dl>
            {/* Kept here rather than as a banner over the score: it belongs with
                the measurements it qualifies, and a reader who opens this panel is
                already asking where the numbers came from. */}
            {result.climate_provenance?.interpolated === true && (
              <p className="mt-5 border-t border-white/10 pt-4 text-xs leading-relaxed text-ink-3">
                No measured cell falls inside your boundary, so these figures were
                interpolated from the nearest measured cells —{' '}
                {result.climate_provenance.source_districts.join(', ')} — the closest{' '}
                {result.climate_provenance.nearest_source_km.toFixed(0)} km away.
              </p>
            )}

            <p className="mt-5 border-t border-white/10 pt-4 text-xs leading-relaxed text-ink-3">
              Observed {result.data_source['observation_start'] ?? '—'} to{' '}
              {result.data_source['observation_end'] ?? '—'}. Wet hours is the fraction
              of sampled hours with rainfall, used instead of an annual total because
              the source accumulates over one hour per day — an annual depth would
              require assuming a daily cycle the data does not contain.
            </p>
          </Popup>
        </div>
      )}
    </PageShell>
  );
}

/**
 * Whether a finding's `required`/`provided` really are "the limit" and "what you
 * specified".
 *
 * For grade, cement content and water/cement ratio they are. The walling check is
 * different: it reports the *climate's* humidity against the threshold at which
 * corrosion accelerates, and decides compliance from whether the chosen material
 * suits that climate. Rendering those two numbers under "Code needs" and "You
 * have" said the user supplied 81.4 where 75 was required and still failed, which
 * is not what happened. Rows like that show their message instead.
 */
function isSpecComparison(parameter: string): boolean {
  return parameter !== 'walling_climate_suitability';
}

/**
 * Trims a finding value to a sensible number of decimals.
 *
 * These arrive as raw floats — a humidity of 81.41115885900099 was being printed
 * in full. Grades and cement contents are whole numbers; a water/cement ratio
 * needs two places.
 */
function formatFindingValue(value: number): string {
  return Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2);
}

function Measurement({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-[0.12em] text-ink-3">{label}</dt>
      <dd className="tabular mt-1 text-xl font-semibold text-ink-1">{value}</dd>
    </div>
  );
}
