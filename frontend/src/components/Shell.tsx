/**
 * Chrome shared by every route: the step rail, the drifting background, and the
 * guard that stops a page being reached before its prerequisites exist.
 */
import { motion, useReducedMotion } from 'motion/react';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { useSession } from '@/state/session-context';
import { useVoice } from '@/state/voice-context';

/** The flow, in order. The rail and the guard both read from this one list. */
export const STEPS = [
  { path: '/', label: 'Location' },
  { path: '/exposure', label: 'Exposure' },
  { path: '/mode', label: 'Approach' },
  { path: '/materials', label: 'Materials' },
  { path: '/score', label: 'Score' },
] as const;

/**
 * Every step after the first needs a district, because a score without one is
 * meaningless. Rather than rendering a broken page, send the user back to pick one.
 * This also covers the case of someone opening a deep link cold.
 */
export function RequireSite({ children }: { children: ReactNode }) {
  const { spec, area } = useSession();
  const location = useLocation();

  // Either a drawn boundary or a named district will do, but one is required: a
  // score with no site is meaningless, so send the user back rather than render a
  // page that would ask the API to score nothing.
  if (spec.district === '' && area === null) {
    return <Navigate to="/" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

/**
 * App-wide switch for Tamil narration.
 *
 * Hidden entirely when the server has no key configured — offering a toggle for
 * something that cannot happen is worse than offering nothing.
 */
export function VoiceToggle() {
  const { enabled, supported, setEnabled } = useVoice();

  if (!supported) {
    return null;
  }

  return (
    <button
      type="button"
      onClick={() => {
        setEnabled(!enabled);
      }}
      aria-pressed={enabled}
      aria-label={enabled ? 'Turn off Tamil voice explanations' : 'Turn on Tamil voice explanations'}
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.12em] transition-colors ${
        enabled
          ? 'border-atmos/50 bg-atmos/12 text-atmos'
          : 'border-white/12 text-ink-3 hover:text-ink-2'
      }`}
    >
      <span aria-hidden="true">{enabled ? '🔊' : '🔇'}</span>
      தமிழ்
    </button>
  );
}

export function StepRail() {
  const location = useLocation();
  const activeIndex = STEPS.findIndex((step) => step.path === location.pathname);

  return (
    <nav aria-label="Progress" className="flex flex-wrap items-center gap-2">
      {STEPS.map((step, index) => {
        const state =
          index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'upcoming';
        return (
          <div key={step.path} className="flex items-center gap-2">
            <span
              aria-current={state === 'active' ? 'step' : undefined}
              className={`text-[11px] font-medium uppercase tracking-[0.14em] transition-colors ${
                state === 'active'
                  ? 'text-atmos'
                  : state === 'done'
                    ? 'text-ink-2'
                    : 'text-ink-3/50'
              }`}
            >
              {step.label}
            </span>
            {index < STEPS.length - 1 && (
              <span aria-hidden="true" className="h-px w-5 bg-white/12" />
            )}
          </div>
        );
      })}
      <VoiceToggle />
    </nav>
  );
}

/**
 * The standard page frame for everything except the globe.
 *
 * The globe opts out because it owns the whole viewport and supplies its own
 * background — the earth *is* the background there.
 */
export function PageShell({
  eyebrow,
  title,
  lead,
  children,
  wide = false,
}: {
  eyebrow: string;
  title: string;
  lead?: string | undefined;
  children: ReactNode;
  wide?: boolean;
}) {
  const reduced = useReducedMotion();

  return (
    <div className="relative min-h-full overflow-hidden">
      {/* Two slow-drifting colour fields. Purely atmospheric, so hidden from
          assistive technology and stilled under reduced-motion. */}
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="aurora absolute -left-1/4 -top-1/3 h-[70vh] w-[70vw] rounded-full bg-atmos-deep/20 blur-[120px]" />
        <div
          className="aurora absolute -bottom-1/3 -right-1/4 h-[60vh] w-[60vw] rounded-full bg-atmos/10 blur-[120px]"
          style={{ animationDelay: '-13s' }}
        />
      </div>

      <div
        className={`relative mx-auto flex min-h-full flex-col px-6 py-10 ${
          wide ? 'max-w-5xl' : 'max-w-2xl'
        }`}
      >
        <header className="mb-8 flex flex-col gap-5">
          <StepRail />
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-atmos">
              {eyebrow}
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink-1 sm:text-4xl">
              {title}
            </h1>
            {lead !== undefined && (
              <p className="mt-3 max-w-prose text-[15px] leading-relaxed text-ink-2">{lead}</p>
            )}
          </div>
        </header>

        <motion.main
          className="flex-1"
          initial={reduced === true ? false : { opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={reduced === true ? { duration: 0 } : { duration: 0.45, delay: 0.06 }}
        >
          {children}
        </motion.main>
      </div>
    </div>
  );
}
