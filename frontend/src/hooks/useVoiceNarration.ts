/**
 * Fetches and plays Tamil narration, with the global on/off preference.
 *
 * Two rules shape this:
 *
 * 1. Voice never blocks the form. Every failure path ends with the control
 *    disappearing or going quiet, never with an error the user must dismiss —
 *    the questions are on screen as text regardless.
 * 2. Audio is fetched from our own backend, never from Sarvam directly, so no key
 *    reaches the browser.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { apiClient } from '@/lib/api-client';

const PREFERENCE_KEY = 'voice-narration-enabled';

/** Whether the user has switched narration on. Defaults to on when unset. */
export function readVoicePreference(): boolean {
  if (typeof localStorage === 'undefined') {
    return true;
  }
  return localStorage.getItem(PREFERENCE_KEY) !== 'off';
}

export function writeVoicePreference(enabled: boolean): void {
  localStorage.setItem(PREFERENCE_KEY, enabled ? 'on' : 'off');
}

/**
 * Object URLs for audio already fetched this session.
 *
 * Module-level so it survives remounts: stepping back to a question should replay
 * instantly rather than re-synthesising. The backend caches too, but this also
 * saves the round trip.
 */
const audioCache = new Map<string, string>();

export type VoiceStatus = 'idle' | 'loading' | 'playing' | 'unavailable';

export function useVoiceNarration(text: string) {
  const [status, setStatus] = useState<VoiceStatus>('idle');
  const audioRef = useRef<HTMLAudioElement | null>(null);
  // Guards against a slow fetch resolving after the component has gone, and
  // against an earlier request overwriting a later one.
  const requestRef = useRef(0);

  const stop = useCallback(() => {
    const audio = audioRef.current;
    if (audio !== null) {
      audio.pause();
      audio.currentTime = 0;
    }
    setStatus((current) => (current === 'unavailable' ? current : 'idle'));
  }, []);

  useEffect(() => stop, [stop]);

  const play = useCallback(async () => {
    if (status === 'playing') {
      stop();
      return;
    }

    const token = ++requestRef.current;
    setStatus('loading');

    try {
      let url = audioCache.get(text);
      if (url === undefined) {
        const blob = await apiClient.narrate(text);
        if (requestRef.current !== token) {
          return;
        }
        url = URL.createObjectURL(blob);
        audioCache.set(text, url);
      }

      const audio = audioRef.current ?? new Audio();
      audioRef.current = audio;
      audio.src = url;
      audio.onended = () => {
        setStatus('idle');
      };
      // A play() rejection is almost always the browser's autoplay policy, which
      // is not a fault worth reporting — the user simply has to press the button.
      await audio.play();
      if (requestRef.current === token) {
        setStatus('playing');
      }
    } catch {
      // Deliberately silent. Voice is an enhancement; the question is already
      // readable on screen, so a failure hides the control rather than
      // interrupting whatever the user was doing.
      if (requestRef.current === token) {
        setStatus('unavailable');
      }
    }
  }, [text, status, stop]);

  return { status, play, stop };
}

/**
 * Whether the server can synthesise at all, asked once per session.
 *
 * Checked before any Listen button renders. Showing a control that cannot work is
 * worse than showing none, because the user only discovers the gap after pressing
 * it and waiting.
 */
export function useVoiceAvailable(): boolean {
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .getVoiceCapabilities()
      .then((capabilities) => {
        if (!cancelled) {
          setAvailable(capabilities.available);
        }
      })
      .catch(() => {
        // No keys configured, or the backend is down. Either way: no voice, and
        // nothing to tell the user about.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return available;
}
