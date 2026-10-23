/**
 * Shared presentational components.
 *
 * These exist so repeated Tailwind class strings become one named component
 * rather than being copied between screens. No business logic lives here.
 *
 * Everything is built to sit *over* the globe: glass surfaces, no opaque white,
 * and no assumption about what is behind the element.
 */
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useEffect, useId, useRef, type ReactNode } from 'react';

import { ApiError } from '@/lib/api-client';

/** One spring, used for every entrance in the app, so motion feels like one hand. */
export const SPRING = { type: 'spring', stiffness: 420, damping: 34, mass: 0.9 } as const;

export function Panel({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`glass rounded-2xl ${className}`}>{children}</div>;
}

export function Button({
  children,
  onClick,
  disabled = false,
  variant = 'primary',
  type = 'button',
  full = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: 'primary' | 'secondary' | 'ghost';
  type?: 'button' | 'submit';
  full?: boolean;
}) {
  const base =
    'btn-3d inline-flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-semibold tracking-tight';

  // The hard bottom edge is what gives the key its depth, so each variant defines
  // its own darker edge colour rather than sharing one shadow.
  const styles: Record<string, string> = {
    primary:
      'bg-atmos text-void shadow-[0_3px_0_var(--color-atmos-deep),0_8px_24px_-6px_oklch(0.78_0.13_220/0.5)]',
    secondary:
      'bg-slate-2 text-ink-1 shadow-[0_3px_0_var(--color-slate-1)] border border-white/10',
    ghost: 'text-ink-2 hover:text-ink-1 shadow-none',
  };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${styles[variant] ?? ''} ${full ? 'w-full' : ''}`}
    >
      {children}
    </button>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <p role="status" className="flex items-center gap-2.5 text-sm text-ink-2">
      <span
        aria-hidden="true"
        className="h-4 w-4 animate-spin rounded-full border-2 border-white/15 border-t-atmos"
      />
      {label}
    </p>
  );
}

/**
 * Renders a failure in a way the user can act on.
 *
 * A missing third-party credential is presented as a setup step rather than a
 * fault, because that is what it is — and the correlation ID is always shown so a
 * report can be tied to server logs.
 */
export function ErrorNotice({ error }: { error: unknown }) {
  const setup = error instanceof ApiError && error.isSetupIssue;
  const tone = setup
    ? 'border-signal/40 bg-signal/10 text-signal'
    : 'border-band-poor/40 bg-band-poor/10 text-band-poor';

  return (
    <div role="alert" className={`rounded-xl border p-4 text-sm ${tone}`}>
      <p className="font-semibold">
        {error instanceof ApiError
          ? setup
            ? 'Setup needed'
            : 'Something went wrong'
          : 'Something went wrong'}
      </p>
      <p className="mt-1 text-ink-2">
        {error instanceof Error ? error.message : 'An unexpected error occurred.'}
      </p>
      {error instanceof ApiError && error.requestId !== undefined && (
        <p className="mt-2 font-mono text-xs text-ink-3">Request ID: {error.requestId}</p>
      )}
    </div>
  );
}

export function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.12em] text-ink-3">{label}</p>
      <p className={`tabular mt-1 text-2xl font-semibold ${accent ?? 'text-ink-1'}`}>{value}</p>
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-ink-1">
        {label}
      </label>
      {hint !== undefined && <p className="mt-0.5 text-xs text-ink-3">{hint}</p>}
      <div className="mt-2">{children(id)}</div>
    </div>
  );
}

/** The one input skin, so no screen re-derives it. */
export const CONTROL =
  'w-full rounded-lg border border-white/12 bg-white/[0.04] px-3.5 py-2.5 text-sm text-ink-1 ' +
  'transition-colors hover:border-white/20 focus:border-atmos focus:outline-none';

/**
 * A modal popup.
 *
 * Focus is moved into the dialog on open and Escape closes it — without both, a
 * glass overlay is decoration rather than a dialog. `AnimatePresence` is what lets
 * it animate *out*; a plain conditional render would snap away.
 */
export function Popup({
  open,
  title,
  description,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const titleId = useId();

  useEffect(() => {
    if (!open) {
      return;
    }
    panelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', onKey);
    // The page behind must not scroll while a dialog is up.
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduced === true ? 0 : 0.18 }}
        >
          <div
            className="absolute inset-0 bg-void/70 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            className="glass relative w-full max-w-lg rounded-2xl p-6 focus:outline-none"
            initial={reduced === true ? false : { opacity: 0, y: 28, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced === true ? { opacity: 0 } : { opacity: 0, y: 16, scale: 0.98 }}
            transition={reduced === true ? { duration: 0 } : SPRING}
          >
            <h2 id={titleId} className="text-lg font-semibold tracking-tight text-ink-1">
              {title}
            </h2>
            {description !== undefined && (
              <p className="mt-1 text-sm text-ink-3">{description}</p>
            )}
            <div className="mt-5">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/**
 * A large, tappable choice. Used wherever a `<select>` would have been for a small
 * set of options — five exposure classes read far better as cards with their
 * plain-language hint visible than as a collapsed dropdown.
 */
export function ChoiceCard({
  label,
  hint,
  selected,
  onSelect,
}: {
  label: string;
  hint: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`btn-3d w-full rounded-xl border p-4 text-left transition-colors ${
        selected
          ? 'border-atmos/60 bg-atmos/12 shadow-[0_3px_0_var(--color-atmos-deep)]'
          : 'border-white/10 bg-white/[0.03] hover:border-white/25 shadow-[0_3px_0_rgba(0,0,0,0.35)]'
      }`}
    >
      <span
        className={`block text-sm font-semibold ${selected ? 'text-atmos' : 'text-ink-1'}`}
      >
        {label}
      </span>
      <span className="mt-0.5 block text-xs text-ink-3">{hint}</span>
    </button>
  );
}
