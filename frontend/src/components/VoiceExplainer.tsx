/**
 * The "Listen" control that reads a question and its options aloud in Tamil.
 *
 * Renders nothing at all when narration is unavailable or switched off, rather
 * than a disabled button. A dead control invites a press and then explains
 * nothing; absence is quieter and equally informative.
 *
 * It never gates the form. The user can select an option while audio is still
 * playing, and pressing again stops it — so narration can always be escaped.
 */
import { useVoiceNarration } from '@/hooks/useVoiceNarration';

export function VoiceExplainer({
  text,
  enabled,
  label = 'கேளுங்கள்',
  className = '',
}: {
  /** The finished Tamil sentence to read, question and options together. */
  text: string;
  /** The global preference plus server availability, resolved by the caller. */
  enabled: boolean;
  label?: string;
  className?: string;
}) {
  const { status, play } = useVoiceNarration(text);

  if (!enabled || status === 'unavailable') {
    return null;
  }

  const busy = status === 'loading';
  const playing = status === 'playing';

  return (
    <button
      type="button"
      onClick={() => {
        void play();
      }}
      // Both states named in English for screen readers, since the surrounding
      // interface is English and a reader will be set to that voice.
      aria-label={playing ? 'Stop the Tamil explanation' : 'Listen to this question in Tamil'}
      aria-pressed={playing}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
        playing
          ? 'border-atmos/60 bg-atmos/15 text-atmos'
          : 'border-white/15 bg-white/[0.04] text-ink-2 hover:border-white/30 hover:text-ink-1'
      } ${className}`}
    >
      <span aria-hidden="true" className="text-sm leading-none">
        {playing ? '⏸' : '🔊'}
      </span>
      <span>{playing ? 'நிறுத்து' : label}</span>
      {busy && (
        <span
          aria-hidden="true"
          className="h-3 w-3 animate-spin rounded-full border border-white/20 border-t-atmos"
        />
      )}
      {playing && (
        // A moving bar is the clearest signal that sound is coming out, for a
        // user who has their volume down or is not sure it started.
        <span aria-hidden="true" className="flex items-end gap-0.5">
          {[0, 1, 2].map((bar) => (
            <span
              key={bar}
              className="w-0.5 animate-pulse rounded-full bg-atmos"
              style={{ height: `${String(5 + bar * 3)}px`, animationDelay: `${String(bar * 120)}ms` }}
            />
          ))}
        </span>
      )}
    </button>
  );
}
