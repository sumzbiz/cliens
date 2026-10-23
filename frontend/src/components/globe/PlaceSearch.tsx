/**
 * Place search over the globe.
 *
 * Takes an address, place name or postcode and flies the camera there. It searches
 * the whole planet on purpose: whether somewhere can be *scored* is a separate
 * question, answered when an area is drawn. Hiding unscoreable places from search
 * would leave the user unable to navigate their own map — and would answer "why
 * can't I find my town?" with silence instead of an explanation.
 */
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { CONTROL, SPRING } from '@/components/ui';
import { ApiError, apiClient } from '@/lib/api-client';
import type { GeocodeMatch } from '@/types/api';
import { useLanguage } from '@/state/language-context';

/**
 * Delay before a keystroke becomes a request.
 *
 * The geocoder is a free public service whose usage policy asks for restraint, so
 * this is deliberately longer than the usual snappy 150 ms — one request per pause
 * in typing rather than one per letter.
 */
const DEBOUNCE_MS = 450;

/**
 * Span assumed for a result the geocoder gave as a point rather than an area.
 *
 * A street address has no extent, so this is the plot-sized window to frame it in
 * — small enough to see the building, not so small the surroundings vanish.
 */
const POINT_SPAN_DEGREES = 0.004;

export function PlaceSearch({
  onPick,
}: {
  /** Reports where to go and how wide the match is, in degrees. */
  onPick: (latitude: number, longitude: number, spanDegrees: number) => void;
}) {
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState<readonly GeocodeMatch[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const { language } = useLanguage();

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setMatches([]);
      setError(null);
      return;
    }

    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(() => {
      apiClient
        .geocode(trimmed)
        .then((response) => {
          if (cancelled) {
            return;
          }
          setMatches(response.matches);
          setError(response.matches.length === 0 ? `Nothing found for “${trimmed}”.` : null);
        })
        .catch((cause: unknown) => {
          if (!cancelled) {
            setMatches([]);
            setError(
              cause instanceof ApiError ? cause.message : language === 'ta' ? 'இடத் தேடல் தோல்வியடைந்தது.' : 'The place search failed.'
            );
          }
        })
        .finally(() => {
          if (!cancelled) {
            setSearching(false);
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      // Cancels both the pending timer and any in-flight response, so an early
      // keystroke can never overwrite the results of a later one.
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, language]);

  // Clicking away closes the results without clearing what was typed, so the
  // search can be reopened without retyping it.
  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (
        containerRef.current !== null &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, []);

  const choose = useCallback(
    (match: GeocodeMatch) => {
      // Frame the bounding box when the geocoder gave one, so a city arrives at
      // its own extent rather than at an arbitrary height. A street address has no
      // box, so it gets a plot-sized window rather than one invented around it.
      const { south, north, west, east } = match;
      const span =
        south != null && north != null && west != null && east != null
          ? Math.max(north - south, east - west)
          : POINT_SPAN_DEGREES;

      onPick(match.latitude, match.longitude, span);
      setOpen(false);
    },
    [onPick]
  );

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <div className="relative">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-3"
        >
          ⌕
        </span>
        <input
          type="search"
          className={`${CONTROL} glass pl-9`}
          placeholder={language === 'ta' ? 'இடம், முகவரி அல்லது அஞ்சல் குறியீட்டைத் தேடுங்கள்' : 'Search a place, address or PIN code'}
          aria-label={language === 'ta' ? 'இடத்தைத் தேடுங்கள்' : 'Search for a place'}
          value={query}
          onFocus={() => {
            setOpen(true);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
        />
        {searching && (
          <span
            aria-hidden="true"
            className="absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin rounded-full border-2 border-white/15 border-t-atmos"
          />
        )}
      </div>

      <AnimatePresence>
        {open && (matches.length > 0 || error !== null) && (
          <motion.div
            className="glass absolute left-0 right-0 top-full z-20 mt-2 max-h-80 overflow-y-auto rounded-xl p-1.5"
            initial={reduced === true ? false : { opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduced === true ? { opacity: 0 } : { opacity: 0, y: -8 }}
            transition={reduced === true ? { duration: 0 } : SPRING}
          >
            {error !== null && <p className="px-3 py-3 text-sm text-ink-3">{error}</p>}
            <ul>
              {matches.map((match) => (
                <li key={`${String(match.latitude)},${String(match.longitude)}`}>
                  <button
                    type="button"
                    onClick={() => {
                      choose(match);
                    }}
                    className="w-full rounded-lg px-3 py-2.5 text-left text-sm text-ink-2 transition-colors hover:bg-white/[0.06] hover:text-ink-1"
                  >
                    {match.label}
                  </button>
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>

      <p className="mt-1.5 px-1 text-[10px] text-ink-3/70">
        {language === 'ta' ? 'இடத் தேடல் © OpenStreetMap பங்களிப்பாளர்கள்' : 'Place search © OpenStreetMap contributors'}
      </p>
    </div>
  );
}
