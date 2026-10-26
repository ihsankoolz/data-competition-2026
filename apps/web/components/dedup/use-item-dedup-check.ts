"use client";

import { useEffect, useMemo, useState } from "react";

import { api, isApiError, type Schema } from "@/lib/api/client";
import type { FieldValues } from "@/lib/forms/schema";

import { DEBOUNCE_MS } from "./use-dedup-check";

export type ItemDedupResult = Schema<"ItemDedupResult">;

export type ItemDedupState =
  | { status: "idle" }
  | { status: "checking"; previous: ItemDedupResult | null }
  | { status: "done"; result: ItemDedupResult }
  | { status: "unavailable"; message: string };

type Settled =
  | { key: string; kind: "done"; result: ItemDedupResult }
  | { key: string; kind: "unavailable"; message: string };

function unavailableMessage(e: unknown): string {
  if (isApiError(e) && e.offline) {
    return "The duplicate check can't reach the server right now. It will run again when you submit.";
  }
  return isApiError(e) ? e.message : "The duplicate check did not finish. Keep typing to retry.";
}

/** Only what the item check looks at: the name, group, catalogue number and registration numbers. */
function pickItemFields(fields: FieldValues): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const name = typeof fields.ItemName === "string" ? fields.ItemName.trim() : "";
  if (name) out.ItemName = name;
  const cat =
    typeof fields.manufacturer_catalogue_no === "string"
      ? fields.manufacturer_catalogue_no.trim()
      : "";
  if (cat) out.manufacturer_catalogue_no = cat;
  if (typeof fields.ItemsGroupCode === "number") out.ItemsGroupCode = fields.ItemsGroupCode;
  const regs = Array.isArray(fields.registrations)
    ? (fields.registrations as { country?: unknown; reg_no?: unknown }[])
        .filter((r) => typeof r?.reg_no === "string" && r.reg_no.trim() && r.country)
        .map((r) => ({ country: String(r.country), reg_no: String(r.reg_no).trim() }))
    : [];
  if (regs.length) out.registrations = regs;
  return out;
}

/**
 * Runs `/dedup/check-item` 400 ms after the person stops typing (session 13), like the
 * customer check. Rules only; it never links anything.
 */
export function useItemDedupCheck(opts: {
  enabled: boolean;
  fields: FieldValues;
  requestId: string | null;
}): ItemDedupState {
  const { enabled, fields, requestId } = opts;
  const query = useMemo(() => pickItemFields(fields), [fields]);
  const name = typeof query.ItemName === "string" ? query.ItemName : "";
  const worthChecking =
    enabled && (name.length >= 3 || !!query.manufacturer_catalogue_no || !!query.registrations);
  const key = worthChecking ? JSON.stringify(query) : "";

  const [settled, setSettled] = useState<Settled | null>(null);
  const [lastResult, setLastResult] = useState<ItemDedupResult | null>(null);

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api
        .POST("/dedup/check-item", {
          body: { fields: query, request_id: requestId },
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
    // `query` is captured by `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, requestId]);

  if (!key) return { status: "idle" };
  if (!settled || settled.key !== key) return { status: "checking", previous: lastResult };
  if (settled.kind === "done") return { status: "done", result: settled.result };
  return { status: "unavailable", message: settled.message };
}
