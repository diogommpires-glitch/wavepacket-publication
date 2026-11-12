import { useEffect, useState } from 'react';
import type { Config, UnitScales } from './types';
import { api } from './types';

export function useCanonicalDraft(config: Config | null) {
  const key = config ? JSON.stringify(config) : null;
  const [result, setResult] = useState<{
    draft: Config;
    key: string;
    config: Config | null;
    errors: string[];
  } | null>(null);
  useEffect(() => {
    if (!key || !config) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const resolved = await api<Config>('/config/resolve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: key,
          signal: controller.signal,
        });
        if (!controller.signal.aborted)
          setResult({ draft: config, key, config: resolved, errors: [] });
      } catch (error) {
        if (!controller.signal.aborted)
          setResult({ draft: config, key, config: null, errors: [(error as Error).message] });
      }
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [config, key]);
  const current = result?.key === key && result.draft === config ? result : null;
  return {
    checking: key !== null && current === null,
    resolved: current?.config ?? null,
    errors: current?.errors ?? [],
  };
}

export function useCanonicalUnits(length: number | null) {
  const [result, setResult] = useState<{
    length: number;
    units: UnitScales | null;
    error: string;
  } | null>(null);
  useEffect(() => {
    if (length === null) return;
    const controller = new AbortController();
    api<UnitScales>(`/units?length_nm=${encodeURIComponent(length)}`, { signal: controller.signal })
      .then((units) => {
        if (!controller.signal.aborted) setResult({ length, units, error: '' });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setResult({ length, units: null, error: error.message });
      });
    return () => controller.abort();
  }, [length]);
  const current = result && Object.is(result.length, length) ? result : null;
  return {
    units: current?.units ?? null,
    checking: length !== null && current === null,
    error: current?.error ?? '',
  };
}
