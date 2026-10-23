/**
 * The before/after comparison — the one moment the rest of the page defers to.
 *
 * Two columns rising from a shared baseline so the gap between them is a physical
 * height rather than a number the reader has to subtract. The ochre is reserved
 * for the gain and appears nowhere else in the interface.
 *
 * The bars grow from zero on mount. That is not decoration: an animated rise makes
 * the *difference* between the two columns legible as motion, which a pair of
 * static rectangles does not convey as immediately.
 */
import { motion, useReducedMotion } from 'motion/react';

import { bandFillClass, bandTextClass, bandVerdict, formatDelta, formatScore } from '@/lib/format';
import type { ScoredSelection } from '@/types/api';

const TRACK_HEIGHT = 220;

function Column({
  scored,
  caption,
  emphasis,
  delay,
}: {
  scored: ScoredSelection;
  caption: string;
  emphasis: boolean;
  delay: number;
}) {
  const reduced = useReducedMotion();
  const height = Math.max((scored.score / 100) * TRACK_HEIGHT, 2);

  return (
    <div className="flex flex-1 flex-col items-center">
      <div
        className="relative w-full"
        style={{ height: TRACK_HEIGHT }}
        // The bar is decorative; the score below carries the value for
        // screen readers, so the visual is hidden from the accessibility tree.
        aria-hidden="true"
      >
        <div
          className="absolute inset-x-0 bottom-0 rounded-t-md bg-white/[0.05]"
          style={{ height: TRACK_HEIGHT }}
        />
        <motion.div
          className={`absolute inset-x-0 bottom-0 rounded-t-md ${bandFillClass(scored.band)}`}
          initial={reduced === true ? false : { height: 2 }}
          animate={{ height }}
          transition={
            reduced === true ? { duration: 0 } : { type: 'spring', stiffness: 90, damping: 18, delay }
          }
        />
      </div>

      <p className={`tabular mt-4 text-5xl font-semibold ${bandTextClass(scored.band)}`}>
        {formatScore(scored.score)}
      </p>
      <p className="text-[11px] uppercase tracking-[0.14em] text-ink-3">{scored.band}</p>
      <p
        className={`mt-1.5 text-center text-sm ${emphasis ? 'font-semibold text-ink-1' : 'text-ink-2'}`}
      >
        {caption}
      </p>
    </div>
  );
}

export function ScoreComparison({
  proposed,
  recommended,
  improvement,
  evaluatedOwnMaterials,
}: {
  proposed: ScoredSelection;
  recommended: ScoredSelection;
  improvement: number;
  evaluatedOwnMaterials: boolean;
}) {
  return (
    <section aria-labelledby="comparison-heading" className="glass rounded-2xl p-6 sm:p-8">
      <h2 id="comparison-heading" className="sr-only">
        Score comparison
      </h2>

      <div className="flex items-end gap-4 sm:gap-8">
        <Column
          scored={proposed}
          caption={evaluatedOwnMaterials ? 'Your specification' : 'Typical local build'}
          emphasis={evaluatedOwnMaterials}
          delay={0.1}
        />

        <div className="flex flex-col items-center pb-28">
          <p className="tabular text-3xl font-semibold text-signal">
            {formatDelta(improvement)}
          </p>
          <p className="text-[11px] uppercase tracking-[0.14em] text-ink-3">points</p>
        </div>

        <Column
          scored={recommended}
          caption="What we'd specify"
          emphasis={!evaluatedOwnMaterials}
          delay={0.25}
        />
      </div>

      <p className="mt-7 border-t border-white/10 pt-5 text-sm leading-relaxed text-ink-2">
        {bandVerdict(proposed.band)}{' '}
        {improvement > 0
          ? `Changing to the specification on the right would gain you ${formatDelta(improvement)} points.`
          : 'The specification on the right would not improve on it.'}
      </p>
    </section>
  );
}
