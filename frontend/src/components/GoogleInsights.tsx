/**
 * Two optional panels beside the score, each backed by a Google service:
 *
 * - `ExplanationPanel`: a plain-language reading of the result, written by Gemini
 *   from the engine's own figures and checked number-by-number on the server.
 * - `ClimateOutlookPanel`: how this site's climate is projected to shift over a
 *   home loan's lifetime, from NASA NEX-GDDP-CMIP6 via Earth Engine.
 *
 * Both are fetched on request, not on mount: each is a paid or slow upstream call,
 * and the score itself never depends on either.
 */
import { useState } from 'react';

import { Button, ErrorNotice, Panel, Spinner } from '@/components/ui';
import { useAction } from '@/hooks/useAction';
import type { ClimateProjection, Explanation, ProjectedVariable } from '@/types/api';

export function ExplanationPanel({ load }: { load: () => Promise<Explanation> }) {
  const { run, loading, error } = useAction(load);
  const [explanation, setExplanation] = useState<Explanation | null>(null);

  return (
    <Panel className="p-6">
      <h2 className="text-base font-semibold text-ink-1">In plain words</h2>
      {explanation === null && !loading && (
        <div className="mt-3">
          <p className="text-sm leading-relaxed text-ink-2">
            A short explanation of this result for someone who is not an engineer.
          </p>
          <div className="mt-4">
            <Button
              variant="secondary"
              onClick={() => {
                void run().then((loaded) => {
                  if (loaded !== null) {
                    setExplanation(loaded);
                  }
                });
              }}
            >
              Explain this result
            </Button>
          </div>
        </div>
      )}
      {loading && (
        <div className="mt-4">
          <Spinner label="Writing the explanation…" />
        </div>
      )}
      {explanation !== null && (
        <div className="mt-3 space-y-3 text-sm leading-relaxed text-ink-2">
          <p className="text-ink-1">{explanation.summary}</p>
          {explanation.points.length > 0 && (
            <ul className="space-y-1.5">
              {explanation.points.map((point) => (
                <li key={point} className="flex gap-2.5">
                  <span aria-hidden="true" className="text-ink-3">
                    —
                  </span>
                  {point}
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-ink-3">
            Written by {explanation.model} from the figures on this page. Every number in it was
            checked against the assessment before it was shown.
          </p>
        </div>
      )}
      {error !== null && (
        <div className="mt-4">
          <ErrorNotice error={error} />
        </div>
      )}
    </Panel>
  );
}

export function ClimateOutlookPanel({ load }: { load: () => Promise<ClimateProjection> }) {
  const { run, loading, error } = useAction(load);
  const [projection, setProjection] = useState<ClimateProjection | null>(null);

  return (
    <Panel className="p-6">
      <h2 className="text-base font-semibold text-ink-1">How this climate is changing</h2>
      {projection === null && !loading && (
        <div className="mt-3">
          <p className="text-sm leading-relaxed text-ink-2">
            Climate model projections for this site over the life of a home loan. Shown for context;
            the score above uses measured climate only.
          </p>
          <div className="mt-4">
            <Button
              variant="secondary"
              onClick={() => {
                void run().then((loaded) => {
                  if (loaded !== null) {
                    setProjection(loaded);
                  }
                });
              }}
            >
              Show the outlook
            </Button>
          </div>
        </div>
      )}
      {loading && (
        <div className="mt-4">
          <Spinner label="Running the climate models — the first time for a place can take up to a minute…" />
        </div>
      )}
      {projection !== null && (
        <div className="mt-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 text-[11px] uppercase tracking-[0.12em] text-ink-3">
                <th className="pb-2.5 font-medium">Measure</th>
                <th className="pb-2.5 text-right font-medium">
                  {yearSpan(projection.baseline_years)}
                </th>
                <th className="pb-2.5 text-right font-medium">
                  {yearSpan(projection.future_years)}
                </th>
                <th className="pb-2.5 text-right font-medium">Change</th>
              </tr>
            </thead>
            <tbody>
              {projection.variables.map((variable) => (
                <OutlookRow key={variable.name} variable={variable} />
              ))}
            </tbody>
          </table>
          <p className="mt-4 text-xs leading-relaxed text-ink-3">
            {projection.dataset}, scenario {projection.scenario.toUpperCase()}, mean of{' '}
            {String(projection.models.length)} models ({projection.models.join(', ')}). The range
            under each change is the smallest and largest any model projects.
          </p>
        </div>
      )}
      {error !== null && (
        <div className="mt-4">
          <ErrorNotice error={error} />
        </div>
      )}
    </Panel>
  );
}

function OutlookRow({ variable }: { variable: ProjectedVariable }) {
  const unit = variable.unit === '%' ? '%' : ` ${variable.unit}`;
  return (
    <tr className="border-b border-white/[0.06]">
      <td className="py-2.5 pr-3 text-ink-1">{variable.name}</td>
      <td className="tabular py-2.5 text-right text-ink-2">
        {variable.baseline.toFixed(1)}
        {unit}
      </td>
      <td className="tabular py-2.5 text-right text-ink-2">
        {variable.future.toFixed(1)}
        {unit}
      </td>
      <td className="tabular py-2.5 text-right text-ink-1">
        {signed(variable.change)}
        <span className="block text-xs text-ink-3">
          {signed(variable.change_low)} to {signed(variable.change_high)}
        </span>
      </td>
    </tr>
  );
}

function signed(value: number): string {
  const fixed = value.toFixed(2);
  return value > 0 ? `+${fixed}` : fixed;
}

function yearSpan([first, last]: [number, number]): string {
  return `${String(first)}–${String(last)}`;
}
