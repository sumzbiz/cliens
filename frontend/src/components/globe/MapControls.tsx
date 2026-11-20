/**
 * On-screen map controls.
 *
 * These exist because gesture-only navigation is not enough. A wheel is
 * unavailable on a touch device, a trackpad pinch is easily mistaken by the
 * browser for a request to zoom the whole document, and "hold the pencil to draw"
 * is invisible until someone tells you. Explicit buttons make every action
 * reachable, discoverable and keyboard-operable.
 *
 * Pan and draw are two buttons rather than one toggle. A single button that
 * changes meaning when pressed forces the user to read its state before every
 * drag; two buttons show which mode is active without being interrogated.
 */
import type { ReactNode } from 'react';

export type MapMode = 'pan' | 'draw';

function ControlButton({
  label,
  onClick,
  active = false,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={`btn-3d flex h-11 w-11 items-center justify-center rounded-xl text-lg ${
        active
          ? 'bg-atmos text-void shadow-[0_3px_0_var(--color-atmos-deep)]'
          : 'bg-slate-2/90 text-ink-1 shadow-[0_3px_0_var(--color-slate-1)] border border-white/10'
      }`}
    >
      {children}
    </button>
  );
}

export function MapControls({
  mode,
  onModeChange,
  onZoomIn,
  onZoomOut,
}: {
  mode: MapMode;
  onModeChange: (mode: MapMode) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
}) {
  return (
    <div className="pointer-events-auto flex flex-col gap-2">
      <div className="glass flex flex-col gap-1.5 rounded-2xl p-1.5">
        <ControlButton label="Zoom in" onClick={onZoomIn}>
          <span aria-hidden="true">+</span>
        </ControlButton>
        <ControlButton label="Zoom out" onClick={onZoomOut}>
          <span aria-hidden="true">−</span>
        </ControlButton>
      </div>

      <div className="glass flex flex-col gap-1.5 rounded-2xl p-1.5">
        <ControlButton
          label="Move the map"
          active={mode === 'pan'}
          onClick={() => {
            onModeChange('pan');
          }}
        >
          <span aria-hidden="true">✋</span>
        </ControlButton>
        <ControlButton
          label="Draw your site boundary"
          active={mode === 'draw'}
          onClick={() => {
            onModeChange('draw');
          }}
        >
          <span aria-hidden="true">✏️</span>
        </ControlButton>
      </div>
    </div>
  );
}
