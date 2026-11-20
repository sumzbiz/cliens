/**
 * Whether voice narration is on, shared by every page.
 *
 * Two independent facts combine here: whether the server can synthesise at all,
 * and whether the user wants it. A Listen button appears only when both hold, so
 * the pages themselves never have to reason about it.
 */
import { createContext, useContext } from 'react';

export interface VoiceValue {
  /** Server has at least one working key AND the user has voice switched on. */
  enabled: boolean;
  /** Server capability alone — drives whether the toggle is worth showing. */
  supported: boolean;
  setEnabled: (enabled: boolean) => void;
}

export const VoiceContext = createContext<VoiceValue>({
  enabled: false,
  supported: false,
  setEnabled: () => {
    // No-op default: a component outside the provider simply gets no voice,
    // which is the same graceful degradation as an unconfigured server.
  },
});

export function useVoice(): VoiceValue {
  return useContext(VoiceContext);
}
