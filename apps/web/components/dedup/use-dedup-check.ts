"use client";

import { useEffect, useMemo, useState } from "react";

import { api, isApiError, type Schema } from "@/lib/api/client";
import type { Entity, FieldValues } from "@/lib/forms/schema";

export type DedupResult = Schema<"DedupResult">;

/** The fields the duplicate check looks at. Bank details are never sent. */
const CHECKED_FIELDS = [
  "CardName",
  "CardForeignName",
  "FederalTaxID",
  "City",
  "Country",
  "Phone1",
  "EmailAddress",
] as const;

export const DEBOUNCE_MS = 400;

export type DedupState =
  | { status: "idle" }
  | { status: "checking"; previous: DedupResult | null }
  | { status: "done"; result: DedupResult }
  | { status: "unavailable"; message: string };

type Settled =
  | { key: string; kind: "done"; result: DedupResult }
  | { key: string; kind: "unavailable"; message: string };

function unavailableMessage(e: unknown): string {
  if (isApiError(e) && e.offline) {
    return "The duplicate check can't reach the server right now. It will run again when you submit.";
  }
  if (isApiError(e) && e.status === 501) {
    return "The duplicate check isn't switched on in this build yet. It will run again when you submit.";
  }
  return isApiError(e) ? e.message : "The duplicate check did not finish. Keep typing to retry.";
}

/**
 * Runs `/dedup/check` 400 ms after the person stops typing. A newer keystroke
 * cancels the call in flight, so a stale answer never replaces a fresh one.
 */
export function useDedupCheck(opts: {
  enabled: boolean;
  domain: "customer" | "vendor";
  entity: Entity;
  fields: FieldValues;
  requestId: string | null;
}): DedupState {
  const { enabled, domain, entity, fields, requestId } = opts;

  const query = useMemo(() => {
    const picked: Record<string, string> = {};
    for (const k of CHECKED_FIELDS) {
      const v = fields[k];
      if (typeof v === "string" && v.trim()) picked[k] = v.trim();
    }
    return picked;
  }, [fields]);

  const name = query.CardName ?? "";
  const taxId = query.FederalTaxID ?? "";
  const worthChecking = enabled && (name.length >= 3 || taxId.length >= 5);
  const key = worthChecking ? JSON.stringify([domain, entity, query]) : "";

  const [settled, setSettled] = useState<Settled | null>(null);
  const [lastResult, setLastResult] = useState<DedupResult | null>(null);

  // The previous answer is only shown (dimmed) while re-checking the same kind
  // of record. "Start over", or a new domain or entity, forgets it, so stale
  // candidates and a stale block never linger.
  const scope = key ? JSON.stringify([domain, entity]) : "";
  const [prevScope, setPrevScope] = useState(scope);
  if (scope !== prevScope) {
    setPrevScope(scope);
    setLastResult(null);
  }

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api
        .POST("/dedup/check", {
          body: {
            domain,
            entity,
            fields: { CardName: "", ...query },
            request_id: requestId,
          },
          signal: controller.signal,
        })
        .then(
          (result) => {
            setSettled({ key, kind: "done", result });
            setLastResult(result);
          },
          (e: unknown) => {
            if (e instanceof DOMException && e.name === "AbortError") return;
            setSettled({ key, kind: "unavailable", message: unavailableMessage(e) });
          },
        );
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // `query`, `domain` and `entity` are all captured by `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, requestId]);

  if (!key) return { status: "idle" };
  if (!settled || settled.key !== key) return { status: "checking", previous: lastResult };
  if (settled.kind === "done") return { status: "done", result: settled.result };
  return { status: "unavailable", message: settled.message };
}
