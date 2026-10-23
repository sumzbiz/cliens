/**
 * Step 3 — which of the two questions the user is actually asking.
 *
 * The backend answers both regardless: every response carries a proposed side and a
 * recommended side. This page only decides what the *proposed* side is — the user's
 * own specification, or a conventional baseline. Framing that as a fork here is
 * what makes the results page legible.
 */
import { useNavigate } from 'react-router-dom';

import { PageShell } from '@/components/Shell';
import { VoiceExplainer } from '@/components/VoiceExplainer';
import { buildNarration, TA } from '@/lib/narration.ta';
import { useVoice } from '@/state/voice-context';
import { Button } from '@/components/ui';
import { useSession } from '@/state/session-context';
import { useLanguage } from '@/state/language';

export default function ModePage() {
  const { spec, update } = useSession();
  const navigate = useNavigate();
  const voice = useVoice();
  const { t } = useLanguage();

  const choose = (evaluateOwnMaterials: boolean) => {
    update({ evaluateOwnMaterials });
    // Entering a mix only makes sense in the first mode, so the second skips it.
    void navigate(evaluateOwnMaterials ? '/materials' : '/score');
  };

  return (
    <PageShell
      eyebrow="Step 3 of 5"
      title="What do you want to know?"
      lead="Both answers use the same measured climate and the same code checks. The difference is only what gets compared against the recommendation."
      wide
    >
      <VoiceExplainer
        text={buildNarration(TA.mode.question, TA.mode.options)}
        enabled={voice.enabled}
        className="mb-4"
      />

      <div className="grid gap-4 sm:grid-cols-2">
        <ModeCard
          badge={t('Check')}
          title={t('I have a specification')}
          body={t('Enter the concrete mix and walling you plan to use. We score it against IS 456 for your district, show every requirement it meets or misses, and show what we would specify instead.')}
          action={t('Enter my materials')}
          selected={spec.evaluateOwnMaterials}
          onSelect={() => {
            choose(true);
          }}
        />
        <ModeCard
          badge={t('Advise')}
          title={t('Tell me what to use')}
          body={t('Skip the form. We specify a mix and walling that clears the code for your district, and compare it against what typically gets built so you can see the gap.')}
          action={t('Recommend a specification')}
          selected={!spec.evaluateOwnMaterials}
          onSelect={() => {
            choose(false);
          }}
        />
      </div>

      <div className="mt-10">
        <Button
          variant="ghost"
          onClick={() => {
            void navigate('/exposure');
          }}
        >
          <span aria-hidden="true">←</span> {t('Back')}
        </Button>
      </div>
    </PageShell>
  );
}

function ModeCard({
  badge,
  title,
  body,
  action,
  selected,
  onSelect,
}: {
  badge: string;
  title: string;
  body: string;
  action: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`btn-3d glass flex h-full flex-col rounded-2xl p-6 text-left ${
        selected ? 'ring-1 ring-atmos/50' : ''
      }`}
    >
      <span className="w-fit rounded-full bg-atmos/15 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-atmos">
        {badge}
      </span>
      <span className="mt-4 text-xl font-semibold tracking-tight text-ink-1">{title}</span>
      <span className="mt-2 flex-1 text-sm leading-relaxed text-ink-2">{body}</span>
      <span className="mt-5 text-sm font-semibold text-atmos">
        {action} <span aria-hidden="true">→</span>
      </span>
    </button>
  );
}
