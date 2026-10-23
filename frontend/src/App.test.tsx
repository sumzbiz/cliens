/**
 * Route-level tests for the five-step flow.
 *
 * These exist because a module-level import error renders a blank page with no
 * visible clue — the exact failure this suite would have caught before. Rendering
 * real routes means any future import-time crash fails the tests rather than
 * shipping a white screen.
 *
 * The globe is not rendered here: jsdom has no WebGL. `LocationPage` lazily imports
 * it, so a Suspense fallback stands in, and the globe's own import is covered
 * separately in `components/globe/DistrictGlobe.test.tsx`.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import App from './App';
import { SessionProvider } from './state/session';
import { VoiceProvider } from './state/voice';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <VoiceProvider>
          <App />
        </VoiceProvider>
      </SessionProvider>
    </MemoryRouter>
  );
}

describe('App routes', () => {
  it('opens on the location step', async () => {
    // The district request fires on mount; the global fetch guard in
    // test/setup.ts would throw, so it is stubbed to a pending promise here.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {}))
    );

    renderAt('/');

    expect(
      await screen.findByRole('heading', { name: /draw your site/i })
    ).toBeInTheDocument();
  });

  it('redirects a later step back to the start when no site is chosen', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {}))
    );

    // Deep-linking to step 4 with an empty session must not render a form that
    // would score against no site at all — the guard sends it back to step 1.
    renderAt('/materials');

    expect(
      await screen.findByRole('heading', { name: /draw your site/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: /what are you building with/i })
    ).not.toBeInTheDocument();
  });

  it('stays fully usable when voice narration is unavailable', async () => {
    // The whole point of the fallback: with no key configured the server reports
    // unavailable, and the form must be indistinguishable from one that never
    // offered voice — no dead button, no error, no blocked question.
    vi.stubGlobal(
      'fetch',
      // Typed as the string form only: every call in this app goes through the
      // API client, which always passes a URL string.
      vi.fn((input: string) => {
        if (input.includes('/voice/capabilities')) {
          return Promise.resolve(
            new Response(JSON.stringify({ available: false, speaker: '', language: 'ta-IN' }), {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            })
          );
        }
        return new Promise(() => {});
      })
    );

    renderAt('/');

    expect(
      await screen.findByRole('heading', { name: /draw your site/i })
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /listen to this question/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /tamil voice explanations/i })).toBeNull();
  });
});
