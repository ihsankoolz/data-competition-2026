"use client";

import { createContext, use, useCallback, useEffect, useState } from "react";

import { api, isApiError, type Schema } from "@/lib/api/client";
import { useApiOnline } from "@/lib/api/status";

export type ClockState = Schema<"ClockState">;

type ClockContextValue = {
  /** The simulated clock, or null until it has loaded. */
  clock: ClockState | null;
  /** True while a +1 day / reset call is in flight. */
  busy: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  advanceDays: (days: number) => Promise<void>;
  reset: () => Promise<void>;
};

const ClockContext = createContext<ClockContextValue | null>(null);

function message(e: unknown): string {
  return isApiError(e) ? e.message : "The clock could not be updated.";
}

export function ClockProvider({ children }: { children: React.ReactNode }) {
  const online = useApiOnline();
  const [clock, setClock] = useState<ClockState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyResult = useCallback((call: Promise<ClockState>) => {
    return call.then(
      (next) => {
        setClock(next);
        setError(null);
      },
      (e: unknown) => setError(message(e)),
    );
  }, []);

  const refresh = useCallback(() => applyResult(api.GET("/clock")), [applyResult]);

  const mutate = useCallback(async (call: () => Promise<ClockState>) => {
    setBusy(true);
    try {
      setClock(await call());
      setError(null);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const advanceDays = useCallback(
    (days: number) => mutate(() => api.POST("/clock/advance", { body: { days } })),
    [mutate],
  );

  const reset = useCallback(() => mutate(() => api.POST("/clock/reset")), [mutate]);

  // Load on mount and whenever the server comes back online.
  useEffect(() => {
    if (!online) return;
    let current = true;
    api.GET("/clock").then(
      (next) => {
        if (!current) return;
        setClock(next);
        setError(null);
      },
      (e: unknown) => current && setError(message(e)),
    );
    return () => {
      current = false;
    };
  }, [online]);

  // Another tab may have moved the clock; catch up when this one is focused.
  useEffect(() => {
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  return (
    <ClockContext value={{ clock, busy, error, refresh, advanceDays, reset }}>
      {children}
    </ClockContext>
  );
}

export function useClock(): ClockContextValue {
  const ctx = use(ClockContext);
  if (!ctx) throw new Error("useClock must be used inside ClockProvider");
  return ctx;
}
