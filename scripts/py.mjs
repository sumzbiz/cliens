#!/usr/bin/env node
/**
 * Cross-platform launcher for the backend virtualenv.
 *
 * The venv interpreter lives at a different path on Windows (`Scripts/python.exe`)
 * than on POSIX (`bin/python`), and npm scripts have no portable way to express
 * that. Every root-level npm script that runs Python goes through this file so the
 * platform branch exists in exactly one place.
 *
 * Usage:  node scripts/py.mjs <module-or-args...>
 * Example: node scripts/py.mjs -m pytest
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backendDir = join(repoRoot, 'backend');

const candidates =
  process.platform === 'win32'
    ? [join(backendDir, '.venv', 'Scripts', 'python.exe')]
    : [join(backendDir, '.venv', 'bin', 'python3'), join(backendDir, '.venv', 'bin', 'python')];

const interpreter = candidates.find(existsSync);

if (interpreter === undefined) {
  process.stderr.write(
    'No backend virtualenv found.\n' +
      `Looked in: ${candidates.join(', ')}\n` +
      'Create it with the steps in README "Setup instructions".\n'
  );
  process.exit(1);
}

const child = spawn(interpreter, process.argv.slice(2), {
  cwd: backendDir,
  stdio: 'inherit',
});

child.on('error', (error) => {
  process.stderr.write(`Failed to start ${interpreter}: ${error.message}\n`);
  process.exit(1);
});

// Propagate the child's exit status so CI and pre-commit see real failures.
child.on('exit', (code, signal) => {
  process.exit(signal !== null ? 1 : (code ?? 1));
});
