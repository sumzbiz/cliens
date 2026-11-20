/**
 * The optional panels fetch only when asked, then show exactly what came back.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ClimateOutlookPanel, ExplanationPanel } from '@/components/GoogleInsights';
import type { ClimateProjection, Explanation } from '@/types/api';

const EXPLANATION: Explanation = {
  summary: 'The cover falls short of the code.',
  points: ['Raise the cover to 45 mm.'],
  model: 'test-model',
  verified: true,
};

const PROJECTION: ClimateProjection = {
  latitude: 13.08,
  longitude: 80.27,
  scenario: 'ssp245',
  models: ['A', 'B'],
  baseline_years: [2025, 2034],
  future_years: [2046, 2055],
  dataset: 'NASA/GDDP-CMIP6',
  variables: [
    {
      name: 'Mean daily maximum temperature',
      unit: '°C',
      baseline: 33.41,
      future: 34.17,
      change: 0.76,
      change_low: 0.55,
      change_high: 1.09,
    },
  ],
};

describe('ExplanationPanel', () => {
  it('asks for the explanation only when the button is pressed', async () => {
    const load = vi.fn(() => Promise.resolve(EXPLANATION));
    render(<ExplanationPanel load={load} />);

    expect(load).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Explain this result' }));

    expect(await screen.findByText(EXPLANATION.summary)).toBeInTheDocument();
    expect(screen.getByText('Raise the cover to 45 mm.')).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(1);
  });
});

describe('ClimateOutlookPanel', () => {
  it('shows each projected change with its model range', async () => {
    render(<ClimateOutlookPanel load={() => Promise.resolve(PROJECTION)} />);

    await userEvent.click(screen.getByRole('button', { name: 'Show the outlook' }));

    expect(await screen.findByText('Mean daily maximum temperature')).toBeInTheDocument();
    expect(screen.getByText('+0.76')).toBeInTheDocument();
    expect(screen.getByText('+0.55 to +1.09')).toBeInTheDocument();
    expect(screen.getByText('2046–2055')).toBeInTheDocument();
  });
});
