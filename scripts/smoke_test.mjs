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
 * failed when that credential is absent, because an unconfigured Earth Engine or
 * Gemini key is a setup state, not a defect. Anything else failing is a real
 * failure and exits non-zero.
 */
const BASE_URL = process.env.SMOKE_BASE_URL ?? 'http://127.0.0.1:8010';

/** A site in Chennai, near the Adyar estuary — the Cyclone Michaung framing. */
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
  process.stdout.write(`Climate Lien Score smoke test against ${BASE_URL}\n\n`);

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

  // --- 5. Score ------------------------------------------------------------
  const scoreRequest = {
    site_id: site.payload.id,
    materials: {
      foundation: 'shallow_strip_footing_masonry',
      walls: 'fired_clay_brick_masonry',
      roofing: 'gi_sheet_roof',
    },
  };
  const proof = await call('POST', '/api/score/prove', scoreRequest);

  if (proof.status === 503 && proof.payload?.error?.code === 'EXTERNAL_SERVICE_UNCONFIGURED') {
    skip('score the site', `${proof.payload.error.details?.service ?? 'a service'} is not configured`);
    skip('apply suggested materials', 'depends on scoring');
    skip('generate report', 'depends on scoring');
    return summarise();
  }

  if (proof.status !== 200) {
    fail('score the site', `status ${String(proof.status)}: ${proof.payload?.error?.message ?? ''}`);
    return summarise();
  }

  const baselineYear = proof.payload.baseline.crossing_year;
  const improvedYear = proof.payload.improved.crossing_year;
  pass('score the site', `crossing year ${baselineYear ?? 'beyond 2055'}`);

  if (proof.payload.baseline.breakdown.years.length === 31) {
    pass('breakdown covers 2025–2055', '31 years');
  } else {
    fail('breakdown covers 2025–2055', `${String(proof.payload.baseline.breakdown.years.length)} years`);
  }

  // The product's central claim: suggested materials must never make it worse.
  const baseline = baselineYear ?? 9999;
  const improved = improvedYear ?? 9999;
  if (improved >= baseline) {
    pass(
      'suggested materials do not worsen the score',
      improved > baseline ? `+${String(improved - baseline)} years` : 'no change'
    );
  } else {
    fail('suggested materials do not worsen the score', `${String(baseline)} → ${String(improved)}`);
  }

  // --- 6. Report -----------------------------------------------------------
  const report = await call('POST', '/api/reports', {
    score_id: proof.payload.baseline.id,
  });
  if (report.status === 503 && report.payload?.error?.code === 'EXTERNAL_SERVICE_UNCONFIGURED') {
    skip('generate report', 'Gemini is not configured (set GEMINI_API_KEY)');
  } else if (report.status === 201 && typeof report.payload?.content === 'string') {
    pass('generate report', `${String(report.payload.content.length)} characters`);
  } else {
    fail('generate report', `status ${String(report.status)}`);
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
