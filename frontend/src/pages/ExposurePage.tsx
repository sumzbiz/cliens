/**
 * Step 2 — how the concrete sits relative to the weather.
 *
 * This drives the IS 456 exposure class, which sets the minimum grade, cement
 * content and water/cement ratio everything downstream is judged against. It gets
 * its own page because it is the single input with the largest effect on the score,
 * and because five choices with real consequences deserve more than a dropdown.
 *
 * The explanation sits beside the choices rather than behind a popup. A popup
 * makes the two mutually exclusive — you cannot read what "buried" implies while
 * looking at the buried card — which is exactly backwards for a decision this
 * consequential. On a narrow screen it falls below the choices instead, since
 * side-by-side stops being readable there.
 */
import { useNavigate } from 'react-router-dom';

import { PageShell } from '@/components/Shell';
import { VoiceExplainer } from '@/components/VoiceExplainer';
import { buildNarration, TA } from '@/lib/narration.ta';
import { useVoice } from '@/state/voice-context';
import { Button, ChoiceCard, ErrorNotice, RequirementsSummary, Spinner } from '@/components/ui';
import { gradeLabel, useSiteRequirements } from '@/hooks/useSiteRequirements';
import { useSession } from '@/state/session-context';
import { ELEMENT_SITUATIONS } from '@/types/api';

/** Consequence text, so a choice is made knowingly rather than guessed at. */
const CONSEQUENCE: Record<string, string> = {
  enclosed: 'Mildest case — the leanest mix the code allows, unless the site is coastal.',
  sheltered: 'Moderate. Salt air near the coast still reaches it, so it tightens there.',
  exposed:
    'Rain, wetting and drying and humidity all count here, so this is usually Severe in Tamil Nadu.',
  buried: 'Moderate inland; near the coast the ground water is brackish and it tightens.',
  tidal: 'The most severe class in IS 456. Expect a high grade and a low w/c ratio.',
};

export default function ExposurePage() {
  const { spec, update, area } = useSession();
  const navigate = useNavigate();
  const voice = useVoice();
  const site = useSiteRequirements(spec.district, area, spec.situation);

  return (
    <PageShell
      eyebrow="Step 2 of 5"
      title="How does the concrete sit?"
      // A drawn outline has no district name — that is resolved server-side when
      // it is scored — so naming one here would print "For ." instead.
      lead={`${
        area === null ? `For ${spec.district}.` : 'For the site you drew.'
      } This decides which IS 456 exposure class applies, and that sets the minimum your specification has to clear.`}
      wide
    >
      <VoiceExplainer
        text={buildNarration(TA.exposure.question, TA.exposure.options)}
        enabled={voice.enabled}
        className="mb-5"
      />

      {/* Choices left, explanation right. `items-start` so the reference panel
          sits at the top rather than stretching to match the taller column. */}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="grid gap-3 sm:grid-cols-2">
          {ELEMENT_SITUATIONS.map((situation) => (
            <ChoiceCard
              key={situation.value}
              label={situation.label}
              hint={situation.hint}
              selected={spec.situation === situation.value}
              onSelect={() => {
                update({ situation: situation.value });
              }}
            />
          ))}

          {/* The class this choice actually produces at this site, live. The
              explainer says the class comes from the answer *and* the measured
              climate; this shows the result instead of leaving it a mystery until
              the score page. */}
          <div aria-live="polite" className="glass rounded-2xl p-5 sm:col-span-2">
            {site.status === 'loading' && <Spinner label="Checking what this site needs…" />}
            {site.status === 'error' && <ErrorNotice error={site.error} />}
            {site.status === 'ready' && (
              <>
                <RequirementsSummary
                  exposureLabel={site.requirements.exposureLabel}
                  minGrade={gradeLabel(site.requirements.minGradeMpa)}
                  minCementKgM3={site.requirements.minCementKgM3}
                  maxWaterCementRatio={site.requirements.maxWaterCementRatio}
                />
                <ul className="mt-4 space-y-1 border-t border-white/10 pt-3 text-xs text-ink-3">
                  {site.requirements.reasons.map((reason) => (
                    <li key={reason}>— {reason}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>

        <aside
          aria-labelledby="exposure-explainer"
          className="glass rounded-2xl p-5 lg:sticky lg:top-6"
        >
          <h2 id="exposure-explainer" className="text-sm font-semibold text-ink-1">
            Why this question decides so much
          </h2>
          <p className="mt-0.5 text-xs text-ink-3">IS 456:2000, Table 3 and Table 5.</p>

          <p className="mt-4 text-sm leading-relaxed text-ink-2">
            The code does not set one standard for all concrete. It sorts an element into an
            exposure class by how much water, salt and air reaches it, then sets a different minimum
            grade, minimum cement content and maximum water/cement ratio for each class.
          </p>

          <ul className="mt-4 space-y-2.5 border-t border-white/10 pt-4">
            {ELEMENT_SITUATIONS.map((situation) => {
              const active = spec.situation === situation.value;
              return (
                <li key={situation.value} className="text-sm">
                  {/* The selected class is highlighted here too, so the panel
                      answers "what did I just pick" as well as "what are these". */}
                  <span className={`font-semibold ${active ? 'text-atmos' : 'text-ink-1'}`}>
                    {situation.label}
                  </span>
                  <span className={active ? 'text-ink-2' : 'text-ink-3'}>
                    {' '}
                    — {CONSEQUENCE[situation.value] ?? ''}
                  </span>
                </li>
              );
            })}
          </ul>

          <p className="mt-4 border-t border-white/10 pt-4 text-xs leading-relaxed text-ink-3">
            Your district&rsquo;s measured humidity, wet hours and distance from the coast are
            combined with this answer to pick the final class. You are not choosing the class
            directly.
          </p>
        </aside>
      </div>

      <div className="mt-10 flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={() => {
            void navigate('/');
          }}
        >
          <span aria-hidden="true">←</span> Back
        </Button>
        <Button
          onClick={() => {
            void navigate('/mode');
          }}
        >
          Continue <span aria-hidden="true">→</span>
        </Button>
      </div>
    </PageShell>
  );
}
