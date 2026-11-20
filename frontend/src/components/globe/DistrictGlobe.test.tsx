/**
 * Import-time guard for the globe.
 *
 * jsdom has no WebGL, so this deliberately does NOT render the globe — that check
 * has to happen in a real browser. What it does cover is the failure that actually
 * shipped a white screen once before: a module-level error in a heavy third-party
 * graphics import, which is invisible until the page is open.
 *
 * The globe is lazily imported, so such an error would surface as a blank panel
 * rather than a build failure. This test makes it a test failure instead.
 */
import { describe, expect, it } from 'vitest';

describe('DistrictGlobe module', () => {
  // Generous timeout: this pulls in three.js, and on a cold Vite cache the
  // transform alone can take over ten seconds. The default 5 s made this fail
  // intermittently on a clean checkout while passing on a warm one.
  it(
    'imports without a module-level error',
    async () => {
      const module = await import('./DistrictGlobe');
      expect(typeof module.DistrictGlobe).toBe('function');
    },
    30_000
  );
});
