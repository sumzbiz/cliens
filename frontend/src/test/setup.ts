/**
 * Vitest global setup.
 *
 * Registers jest-dom matchers and installs guards that make it impossible for a
 * test to silently reach the network — the brief requires that external services
 * are always mocked.
 */
// Matchers are registered explicitly rather than via '@testing-library/jest-dom/vitest'.
// That entry point does a bare `import 'vitest'`, and npm hoists jest-dom to the
// workspace root while vitest stays in frontend/node_modules — so the bare import
// cannot resolve. Extending expect directly sidesteps the hoisting entirely.
import * as matchers from '@testing-library/jest-dom/matchers';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll, expect, vi } from 'vitest';

expect.extend(matchers);

beforeAll(() => {
  // Any test that needs HTTP must mock `fetch` explicitly. An unmocked call
  // fails loudly here rather than hanging or hitting a real server.
  vi.stubGlobal(
    'fetch',
    vi.fn(() => {
      throw new Error(
        'Unmocked fetch() in a test. Mock the API client or stub fetch for this case.'
      );
    })
  );

  // Motion and the globe both read `prefers-reduced-motion`, and jsdom has no
  // matchMedia at all. Reporting "no preference" keeps tests on the same path a
  // default browser takes, rather than silently exercising the reduced branch.
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
  );

  // The globe sizes its WebGL canvas from a ResizeObserver, which jsdom does not
  // implement. A minimal stand-in is installed; combined with the fixed
  // dimensions below, measured components render at a deterministic size.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe(): void {
        // No layout engine in jsdom, so there is nothing to observe.
      }
      unobserve(): void {
        // Intentionally empty.
      }
      disconnect(): void {
        // Intentionally empty.
      }
    }
  );

  // jsdom reports every element as 0x0, which would leave any size-measured
  // component permanently at zero, so give it a deterministic size.
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    value: 1024,
  });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    value: 768,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
