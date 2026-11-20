#!/usr/bin/env node
/**
 * End-to-end smoke test against a running backend.
 *
 *   npm run smoke
 *
 * Walks the same path the README's manual test describes, so the documented
 * instructions are executable rather than merely written down.
 *
 * Steps that need a third-party credential are reported as SKIPPED rather than
 * failed when that credential is absent, because an unconfigured Sarvam key is a
 * setup state, not a defect. Anything else failing is a real failure and exits
 * non-zero.
 */
const BASE_URL = process.env.SMOKE_BASE_URL ?? 'http://127.0.0.1:8010';

/**
 * A site in Chennai, near the Adyar estuary. Chennai is not a district in the
 * measured grid, but a pin there resolves to the nearest cell (Tiruvallur).
 */
const CHENNAI_LON = 80.27;
const CHENNAI_LAT = 13.01;
const SIDE = 0.0004; // roughly 44 m at this latitude

const SITE_POLYGON = {
  type: 'Polygon',
  coordinates: [
    [
      [CHENNAI_LON, CHENNAI_LAT],
      [CHENNAI_LON + SIDE, CHENNAI_LAT],
      [CHENNAI_LON + SIDE, CHENNAI_LAT + SIDE],
      [CHENNAI_LON, CHENNAI_LAT + SIDE],
      [CHENNAI_LON, CHENNAI_LAT],
    ],
  ],
};

let failures = 0;
let skipped = 0;

function pass(step, detail) {
  process.stdout.write(`  PASS  ${step}${detail === undefined ? '' : ` — ${detail}`}\n`);
}

function fail(step, detail) {
  failures += 1;
  process.stdout.write(`  FAIL  ${step} — ${detail}\n`);
}

function skip(step, detail) {
  skipped += 1;
  process.stdout.write(`  SKIP  ${step} — ${detail}\n`);
}

async function call(method, path, body) {
  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const payload = await response.json().catch(() => null);
  return { status: response.status, payload };
}

async function main() {
  process.stdout.write(`CLIENS smoke test against ${BASE_URL}\n\n`);

  // --- 1. Liveness ---------------------------------------------------------
  try {
    const { status, payload } = await call('GET', '/api/health/live');
    if (status === 200 && payload?.status === 'ok') {
      pass('backend is live');
    } else {
      fail('backend is live', `status ${String(status)}`);
      process.stdout.write('\nThe backend is not answering. Start it with: npm run dev:backend\n');
      return 1;
    }
  } catch (error) {
    fail('backend is live', error instanceof Error ? error.message : String(error));
    process.stdout.write('\nCould not reach the backend. Start it with: npm run dev:backend\n');
    return 1;
  }

  // --- 2. Readiness --------------------------------------------------------
  const ready = await call('GET', '/api/health/ready');
  const dependencies = ready.payload?.dependencies ?? [];
  for (const dependency of dependencies) {
    if (dependency.ready === true) {
      pass(`dependency: ${dependency.name}`, dependency.detail ?? undefined);
    } else {
      fail(`dependency: ${dependency.name}`, dependency.detail ?? 'not ready');
    }
  }

  // --- 3. Material catalogue ----------------------------------------------
  const materials = await call('GET', '/api/materials');
  const wallOptions = materials.payload?.walls ?? [];
  if (materials.status === 200 && wallOptions.length > 0) {
    const total =
      (materials.payload.foundation?.length ?? 0) +
      wallOptions.length +
      (materials.payload.roofing?.length ?? 0);
    pass('material catalogue', `${String(total)} materials`);
  } else {
    fail('material catalogue', 'empty — run `npm run db:seed`');
  }

  // --- 4. Site submission --------------------------------------------------
  const site = await call('POST', '/api/sites', {
    geometry: SITE_POLYGON,
    label: 'Smoke test site',
  });
  if (site.status !== 201) {
    fail('submit site polygon', `status ${String(site.status)}`);
    return failures === 0 ? 0 : 1;
  }
  pass('submit site polygon', `area ${Math.round(site.payload.area_sq_ft)} sq ft (PostGIS)`);

  // Area is computed server-side; a wildly wrong figure means a projection or
  // coordinate-order bug, which is exactly what this check is here to catch.
  const areaSqFt = site.payload.area_sq_ft;
  if (areaSqFt > 15_000 && areaSqFt < 28_000) {
    pass('server-computed area is plausible');
  } else {
    fail('server-computed area is plausible', `got ${String(areaSqFt)} sq ft, expected ~21,000`);
  }

  // --- 5. District catalogue ---------------------------------------------
  const districts = await call('GET', '/api/score/districts');
  const madurai = districts.payload?.locations?.find((location) => location.name === 'Madurai');
  if (districts.status === 200 && madurai !== undefined) {
    pass('district catalogue', `${String(districts.payload.districts.length)} districts`);
  } else {
    fail('district catalogue', `status ${String(districts.status)}, Madurai missing`);
    return summarise();
  }

  // --- 6. Score a specification -------------------------------------------
  // A footing in soil: buried exposure, where clause 26.4.2.1's 50 mm footing
  // minimum governs over Table 16, so the cover check is exercised for real.
  const specification = {
    concrete: {
      grade: 'M30',
      cement_content_kg_m3: 340,
      water_cement_ratio: 0.45,
      cement_type: 'PPC',
      admixtures: [],
    },
    walling_material_id: 'fly_ash_brick',
    nominal_cover_mm: 40,
    element_situation: 'buried',
  };
  const scored = await call('POST', '/api/score', {
    district: 'Madurai',
    materials: specification,
    element_situation: 'buried',
    member: 'footing',
  });
  if (scored.status !== 200) {
    fail('score a specification', `status ${String(scored.status)}`);
    return summarise();
  }
  const proposed = scored.payload.proposed;
  pass('score a specification', `${String(proposed.score)} / 100, ${proposed.band}`);

  const cover = proposed.findings.find((finding) => finding.parameter === 'nominal_cover_mm');
  if (cover?.required === 50 && cover.compliant === false) {
    pass('footing cover checked against clause 26.4.2.1', '40 mm short of 50 mm');
  } else {
    fail('footing cover checked against clause 26.4.2.1', JSON.stringify(cover));
  }

  if (scored.payload.recommended.compliant === true) {
    pass('recommendation is compliant', `cover ${String(scored.payload.recommended.nominal_cover_mm)} mm`);
  } else {
    fail('recommendation is compliant', 'the advised specification fails its own checks');
  }

  const life = proposed.service_life;
  if (life.lower_years <= life.years && life.years <= life.upper_years) {
    pass('service life is a range', `${String(life.lower_years)}–${String(life.upper_years)} years`);
  } else {
    fail('service life is a range', JSON.stringify(life));
  }

  // --- 7. Score a drawn area ------------------------------------------------
  const area = await call('POST', '/api/score/area', {
    area: {
      south: madurai.grid_latitude - 0.1,
      north: madurai.grid_latitude + 0.1,
      west: madurai.grid_longitude - 0.1,
      east: madurai.grid_longitude + 0.1,
    },
    materials: specification,
    element_situation: 'buried',
    member: 'footing',
  });
  if (area.status === 200 && typeof area.payload?.climate_provenance?.interpolated === 'boolean') {
    pass('score a drawn area', area.payload.climate_provenance.interpolated ? 'interpolated' : 'measured');
  } else {
    fail('score a drawn area', `status ${String(area.status)}`);
  }

  // --- 8. Report -----------------------------------------------------------
  const report = await fetch(`${BASE_URL}/api/reports`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ district: 'Madurai', materials: specification, member: 'footing' }),
  });
  const pdf = new Uint8Array(await report.arrayBuffer());
  const isPdf = String.fromCharCode(...pdf.slice(0, 5)) === '%PDF-';
  if (report.status === 200 && isPdf) {
    pass('download the PDF report', `${String(pdf.length)} bytes`);
  } else {
    fail('download the PDF report', `status ${String(report.status)}`);
  }

  // --- 9. Refusal outside coverage -----------------------------------------
  // New Delhi is far from every measured cell: it must be refused as not covered,
  // not answered with a confident reading borrowed from Tamil Nadu.
  const outside = await call('POST', '/api/score/resolve', { latitude: 28.61, longitude: 77.21 });
  if (outside.status === 404 && outside.payload?.error?.code === 'LOCATION_NOT_COVERED') {
    pass('refuses a point outside coverage', 'LOCATION_NOT_COVERED');
  } else {
    fail('refuses a point outside coverage', `status ${String(outside.status)}`);
  }

  // --- 10. Voice -------------------------------------------------------------
  const voice = await call('GET', '/api/voice/capabilities');
  if (voice.status === 200 && voice.payload?.available === true) {
    pass('Tamil narration available', voice.payload.speaker);
  } else if (voice.status === 200) {
    skip('Tamil narration', 'no usable Sarvam key (set SARVAM_API_KEY_PRIMARY)');
  } else {
    fail('voice capabilities', `status ${String(voice.status)}`);
  }

  return summarise();
}

function summarise() {
  process.stdout.write(
    `\n${failures === 0 ? 'Smoke test passed' : 'Smoke test FAILED'}` +
      ` — ${String(failures)} failed, ${String(skipped)} skipped.\n`
  );
  if (skipped > 0) {
    process.stdout.write(
      'Skipped steps need third-party credentials. See README "Prerequisites".\n'
    );
  }
  return failures === 0 ? 0 : 1;
}

process.exit(await main());
