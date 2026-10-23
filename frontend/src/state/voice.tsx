/**
 * Resolves voice availability once for the whole app.
 *
 * Asking the server per page would mean several identical requests on every
 * navigation; the answer cannot change within a session.
 */
import { useCallback, useMemo, useState, type ReactNode } from 'react';

import {
  readVoicePreference,
  useVoiceAvailable,
  writeVoicePreference,
} from '@/hooks/useVoiceNarration';
import { VoiceContext, type VoiceValue } from '@/state/voice-context';

export function VoiceProvider({ children }: { children: ReactNode }) {
  const supported = useVoiceAvailable();
  const [wanted, setWanted] = useState(readVoicePreference);

  const setEnabled = useCallback((enabled: boolean) => {
    setWanted(enabled);
    writeVoicePreference(enabled);
  }, []);

  const value = useMemo<VoiceValue>(
    () => ({ enabled: supported && wanted, supported, setEnabled }),
    [supported, wanted, setEnabled]
  );

  return <VoiceContext.Provider value={value}>{children}</VoiceContext.Provider>;
}
