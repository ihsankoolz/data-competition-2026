/** Number formatting and small helpers shared by the regional view and the ops card. */
import type { Schema } from "@/lib/api/client";

export type Caption = Schema<"Caption">;
export type Captions = Record<string, Caption>;

/** "US$11.4M", "US$877k", "US$950". */
export function usdShort(value: number): string {
  const sign = value < 0 ? "-" : "";
  const v = Math.abs(value);
  if (v >= 1_000_000) return `${sign}US$${(v / 1_000_000).toFixed(v >= 10_000_000 ? 1 : 2)}M`;
  if (v >= 1_000) return `${sign}US$${Math.round(v / 1_000)}k`;
  return `${sign}US$${Math.round(v)}`;
}

/** "US$11,351,308". */
export function usdFull(value: number): string {
  const sign = value < 0 ? "-" : "";
  return `${sign}US$${Math.round(Math.abs(value)).toLocaleString("en-US")}`;
}

/** "80.7%". */
export function pct(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`;
}

/** "+1.7%" / "-79.5%"; "new" when there is nothing to compare with. */
export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "new";
  const s = value.toFixed(digits);
  return value > 0 ? `+${s}%` : `${s}%`;
}

/** "3.5" business days; whole numbers lose the ".0". */
export function days(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export const PRODUCT_LABELS: Record<string, string> = {
  A: "Product A, test kits",
  B: "Product B, equipment",
  C: "Product C, services",
};

export const SCENARIO_LABELS: Record<string, string> = {
  seasonal_trend: "Growing and seasonal (demo)",
  flat_noisy: "Flat and noisy",
  intermittent: "Sparse ordering",
};

/** A caption from the API, or a plain fallback so a missing key never breaks the page. */
export function captionOf(captions: Captions | undefined, key: string, fallback: Caption): Caption {
  return captions?.[key] ?? fallback;
}
