"use client";

import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { api, isApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

type Outcome = { ok: boolean; text: string } | null;

/**
 * The history check: asks the API to walk the whole history log (every request) and shows the
 * result in plain words. It only reads; there is deliberately no way to change the log here.
 */
export function HistoryCheckButton({ className }: { className?: string }) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);

  async function run() {
    setBusy(true);
    try {
      const res = await api.GET("/audit/verify");
      setOutcome({
        ok: res.ok,
        text: res.ok
          ? `Checks the whole history log (all requests): ${res.checked} entries intact.`
          : `Checks the whole history log (all requests): ${res.message}`,
      });
    } catch (e) {
      setOutcome({
        ok: false,
        text: isApiError(e) ? e.message : "The check could not run. Try again in a moment.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn("flex flex-col items-start gap-2", className)}>
      <Button
        variant="outline"
        size="sm"
        onClick={run}
        disabled={busy}
        data-testid="history-check-button"
      >
        <ShieldCheck />
        {busy ? "Checking…" : "Check history is untampered"}
      </Button>
      {outcome && (
        <p
          role="status"
          data-testid="history-check-result"
          data-ok={outcome.ok}
          className={cn("text-xs", outcome.ok ? "text-success-foreground" : "text-destructive")}
        >
          {outcome.text}
        </p>
      )}
    </div>
  );
}

/** The Admin & config section: the same check, with a line on why it can be trusted. */
export function HistoryCheck() {
  return (
    <section className="flex max-w-3xl flex-col gap-3" aria-label="History check">
      <h2 className="text-base font-semibold">History check</h2>
      <p className="text-sm text-muted-foreground">
        The history log can only be added to, and each entry is chained to the one before it, so
        any edit shows up here.
      </p>
      <HistoryCheckButton />
    </section>
  );
}
