/**
 * The concrete changes behind "What we'd specify", and a way to adopt them.
 *
 * The recommendation is built by raising the user's own specification only where
 * it falls short, so this list is exactly the advice: every line is something to
 * change, and anything not listed already meets or beats the target.
 */
import { Button, Panel } from '@/components/ui';
import type { SpecChange } from '@/lib/spec-changes';

export function RecommendedChanges({
  changes,
  evaluatedOwnMaterials,
  onAdopt,
}: {
  changes: readonly SpecChange[];
  evaluatedOwnMaterials: boolean;
  onAdopt: () => void;
}) {
  if (changes.length === 0) {
    return null;
  }
  return (
    <Panel className="p-6">
      <h2 className="text-base font-semibold text-ink-1">What we&rsquo;d change</h2>
      <p className="mt-1 text-sm text-ink-3">
        {evaluatedOwnMaterials
          ? 'Only what falls short of the target for this site. Everything else in your specification stays as you chose it.'
          : 'Compared with a typical local build.'}
      </p>
      <ul className="mt-4 divide-y divide-white/[0.06]">
        {changes.map((change) => (
          <li
            key={change.label}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 text-sm"
          >
            <span className="text-ink-1">{change.label}</span>
            <span className="tabular text-ink-2">
              <span className="text-ink-3 line-through decoration-ink-3/60">{change.from}</span>
              <span aria-hidden="true" className="mx-2 text-ink-3">
                →
              </span>
              <span className="sr-only"> changes to </span>
              <span className="font-semibold text-band-good">{change.to}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-5">
        <Button variant="secondary" onClick={onAdopt}>
          Use this specification
        </Button>
      </div>
    </Panel>
  );
}
