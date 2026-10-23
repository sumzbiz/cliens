/**
 * Data-fetching hooks.
 *
 * Components never call the API client directly, so loading and error states are
 * modelled the same way everywhere rather than being re-invented per screen.
 */
import { useCallback, useState } from 'react';

/**
 * Wrap an async action with loading and error state.
 *
 * Used for the submit, score and report actions, which are user-triggered rather
 * than fired on mount.
 */
export function useAction<TArgs extends unknown[], TResult>(
  action: (...args: TArgs) => Promise<TResult>
): {
  run: (...args: TArgs) => Promise<TResult | null>;
  loading: boolean;
  error: unknown;
  reset: () => void;
} {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const run = useCallback(
    async (...args: TArgs): Promise<TResult | null> => {
      setLoading(true);
      setError(null);
      try {
        return await action(...args);
      } catch (caught) {
        setError(caught);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [action]
  );

  const reset = useCallback(() => {
    setError(null);
  }, []);

  return { run, loading, error, reset };
}
