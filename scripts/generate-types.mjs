#!/usr/bin/env node
/**
 * Generates `frontend/src/types/api.generated.ts` from the backend's OpenAPI spec.
 *
 * The brief prefers generation over hand-mirroring, so the Pydantic schemas are the
 * single source of truth for API shapes and the TypeScript types are derived from
 * them. Run this after any schema change:
 *
 *   npm run generate:types
 *
 * The backend must be running (npm run dev:backend) — the spec is read from the
 * live server rather than the source so that what the client is typed against is
 * exactly what the server serves.
 */
import { spawn } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SPEC_URL = process.env.OPENAPI_URL ?? 'http://localhost:8010/openapi.json';
const OUTPUT = join(repoRoot, 'frontend', 'src', 'types', 'api.generated.ts');

async function assertBackendReachable() {
  try {
    const response = await fetch(SPEC_URL, { signal: AbortSignal.timeout(5000) });
    if (!response.ok) {
      throw new Error(`${String(response.status)} ${response.statusText}`);
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    process.stderr.write(
      `Could not read the OpenAPI spec from ${SPEC_URL}\n` +
        `  ${detail}\n\n` +
        'Start the backend first:  npm run dev:backend\n'
    );
    process.exit(1);
  }
}

await assertBackendReachable();

// `shell: true` on Windows: since Node 20 spawning a `.cmd` without a shell is
// rejected with EINVAL, because batch files cannot be executed directly. The
// arguments are all program-controlled, so no untrusted input reaches the shell.
const child = spawn('npx', ['openapi-typescript', SPEC_URL, '--output', OUTPUT], {
  cwd: repoRoot,
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

child.on('error', (error) => {
  process.stderr.write(`Failed to run openapi-typescript: ${error.message}\n`);
  process.exit(1);
});

child.on('exit', (code, signal) => {
  if (signal === null && code === 0) {
    process.stdout.write(`Wrote ${OUTPUT}\n`);
  }
  process.exit(signal !== null ? 1 : (code ?? 1));
});
