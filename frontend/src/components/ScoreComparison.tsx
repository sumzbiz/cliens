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
import { useLanguage } from '@/state/language';

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
      <p className="text-[11px] uppercase tracking-[0.14em] text-ink-3">{scored.compliant ? scored.band : `${scored.band} ? non-compliant`}</p>
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
  const { language } = useLanguage();
  const keepingProposed =
    evaluatedOwnMaterials &&
    proposed.concrete.grade === recommended.concrete.grade &&
    proposed.concrete.cement_content_kg_m3 === recommended.concrete.cement_content_kg_m3 &&
    proposed.concrete.water_cement_ratio === recommended.concrete.water_cement_ratio &&
    proposed.concrete.cement_type === recommended.concrete.cement_type &&
    proposed.concrete.admixtures.join('|') === recommended.concrete.admixtures.join('|') &&
    proposed.walling_material_id === recommended.walling_material_id;

  return (
    <section aria-labelledby="comparison-heading" className="glass rounded-2xl p-6 sm:p-8">
      <h2 id="comparison-heading" className="sr-only">
        Score comparison
      </h2>

      <div className="flex items-end gap-4 sm:gap-8">
        <Column
          scored={proposed}
          caption={language === 'ta' ? (evaluatedOwnMaterials ? 'உங்கள் விவரக்குறிப்பு' : 'வழக்கமான உள்ளூர் கட்டுமானம்') : evaluatedOwnMaterials ? 'Your specification' : 'Typical local build'}
          emphasis={evaluatedOwnMaterials}
          delay={0.1}
        />

        <div className="flex flex-col items-center pb-28">
          <p className="tabular text-3xl font-semibold text-signal">
            {formatDelta(improvement)}
          </p>
          <p className="text-[11px] uppercase tracking-[0.14em] text-ink-3">{language === 'ta' ? 'புள்ளிகள்' : 'points'}</p>
        </div>

        <Column
          scored={recommended}
          caption={language === 'ta' ? (keepingProposed ? 'உங்கள் விவரக்குறிப்பைத் தொடரவும்' : 'எங்கள் பரிந்துரை') : keepingProposed ? 'Keep your specification' : "What we'd specify"}
          emphasis={!evaluatedOwnMaterials}
          delay={0.25}
        />
      </div>

      <p className="mt-7 border-t border-white/10 pt-5 text-sm leading-relaxed text-ink-2">
        {language === 'ta'
          ? keepingProposed
            ? 'உங்கள் விவரக்குறிப்பு ஏற்கனவே விதிமுறைகளைப் பூர்த்தி செய்து, எங்கள் வழக்கமான பரிந்துரையைவிட அதிக மதிப்பெண் பெற்றுள்ளது. இதையே தொடரலாம்.'
            : proposed.compliant
              ? improvement > 0
                ? `உங்கள் விவரக்குறிப்பு விதிமுறைகளைப் பூர்த்தி செய்கிறது. வலதுபுறப் பரிந்துரைக்கு மாறினால் ${formatDelta(improvement)} புள்ளிகள் கிடைக்கும்.`
                : 'வலதுபுறப் பரிந்துரை மதிப்பெண்ணை மேம்படுத்தாது.'
              : improvement > 0
                ? `உங்கள் விவரக்குறிப்பில் விதிமுறைத் தேவைகள் குறைவாக உள்ளன. வலதுபுறப் பரிந்துரைக்கு மாறினால் ${formatDelta(improvement)} புள்ளிகள் கிடைக்கும்.`
                : 'உங்கள் விவரக்குறிப்பு ஒன்று அல்லது அதற்கு மேற்பட்ட விதிமுறைச் சரிபார்ப்புகளில் குறைவாக உள்ளது.'
          : keepingProposed
          ? 'Your specification already meets the code and scores higher than our standard recommendation. We would keep it as specified.'
          : `${
              proposed.compliant
                ? bandVerdict(proposed.band)
                : 'Your specification misses one or more required code checks.'
            } ${
              improvement > 0
                ? `Changing to the specification on the right would gain you ${formatDelta(improvement)} points.`
                : 'The specification on the right would not improve on it.'
            }`}
      </p>
    </section>
  );
}
