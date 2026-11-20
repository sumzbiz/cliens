#!/usr/bin/env node
/**
 * Fails when `frontend/src/types/api.generated.ts` has drifted from the backend.
 *
 *   npm run check:types
 *
 * `generate:types` reads the spec from a running server, so nothing forced the
 * committed file to be regenerated after a schema change — and it was not: the
 * `/api/reports/area` endpoint shipped without ever appearing in it. This check
 * builds the spec offline (`python -m app.cli export-openapi`), generates types
 * from it into a temporary file and compares that with the committed copy, so CI
 * catches the drift without starting a server or a database.
 *
 * Python comes from the backend virtualenv via `scripts/py.mjs`, unless
 * `CLIENS_PYTHON` names an interpreter — CI installs into the runner's own Python
 * rather than a virtualenv, so it sets `CLIENS_PYTHON=python`.
 */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backendDir = join(repoRoot, 'backend');
const COMMITTED = join(repoRoot, 'frontend', 'src', 'types', 'api.generated.ts');

function run(command, args, cwd = repoRoot) {
  // `shell: true` on Windows: since Node 20 spawning a `.cmd` (npx) without a shell
  // is rejected with EINVAL. The arguments are all program-controlled.
  const result = spawnSync(command, args, {
    cwd,
    stdio: 'inherit',
    shell: process.platform === 'win32',
  });
  if (result.status !== 0) {
    process.stderr.write(`Command failed: ${command} ${args.join(' ')}\n`);
    process.exit(1);
  }
}

const workDir = mkdtempSync(join(tmpdir(), 'cliens-types-'));
try {
  const spec = join(workDir, 'openapi.json');
  const generated = join(workDir, 'api.generated.ts');

  const exportArgs = ['-m', 'app.cli', 'export-openapi', spec];
  if (process.env.CLIENS_PYTHON) {
    run(process.env.CLIENS_PYTHON, exportArgs, backendDir);
  } else {
    run('node', [join('scripts', 'py.mjs'), ...exportArgs]);
  }
  run('npx', ['openapi-typescript', spec, '--output', generated]);

  // Line endings are normalised so a Windows checkout with autocrlf does not
  // report drift that exists only in the working tree.
  const normalise = (path) => readFileSync(path, 'utf8').replace(/\r\n/g, '\n');
  if (normalise(generated) !== normalise(COMMITTED)) {
    process.stderr.write(
      'frontend/src/types/api.generated.ts is out of date with the backend schemas.\n' +
        'Regenerate it:  npm run dev:backend  then  npm run generate:types\n'
    );
    process.exit(1);
  }
  process.stdout.write('Frontend API types match the backend OpenAPI spec.\n');
} finally {
  rmSync(workDir, { recursive: true, force: true });
}
