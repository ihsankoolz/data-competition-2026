"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { PRODUCT_LABELS, signedPct, usdFull, usdShort } from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";
import { countryName } from "@/lib/format";

type HeatCell = Schema<"HeatCell">;

// One-hue sequential green ramp on the sage primary hue (~133). Light = small, dark = large.
// Lightness falls in even steps; chroma peaks mid-ramp so the light end stays calm and the dark
// end stays deep rather than neon. Same ramp in light and dark mode.
const RAMP = [
  "oklch(0.95 0.03 133)",
  "oklch(0.91 0.045 133)",
  "oklch(0.87 0.06 133)",
  "oklch(0.83 0.075 133)",
  "oklch(0.79 0.085 133)",
  "oklch(0.74 0.095 133)",
  "oklch(0.69 0.1 133)",
  "oklch(0.63 0.1 133)",
  "oklch(0.57 0.095 134)",
  "oklch(0.51 0.09 134)",
  "oklch(0.45 0.08 135)",
  "oklch(0.39 0.07 135)",
];
// Steps from here on carry white text: white on L 0.57 is about 4.6:1, on the darkest step about
// 9:1. Below it, near-black text on L 0.63 is about 7:1.
const DARK_TEXT_FROM = 8;

const COUNTRIES = ["SG", "MY", "ID", "VN", "TH"] as const;
const PRODUCTS = ["A", "B", "C"] as const;

function step(value: number, max: number): number {
  if (max <= 0) return 0;
  // Square root keeps small equipment and service cells from all collapsing to the lightest step.
  const t = Math.sqrt(Math.max(0, value) / max);
  return Math.min(RAMP.length - 1, Math.round(t * (RAMP.length - 1)));
}

function GrowthMark({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <Minus className="size-3" aria-hidden />;
  if (value > 0) return <ArrowUpRight className="size-3" aria-hidden />;
  if (value < 0) return <ArrowDownRight className="size-3" aria-hidden />;
  return <Minus className="size-3" aria-hidden />;
}

export function Heatmap({ cells, country }: { cells: HeatCell[]; country: string | null }) {
  const max = Math.max(0, ...cells.map((c) => c.value_usd));
  const rows = COUNTRIES.filter((c) => cells.some((cell) => cell.country === c));
  const at = (c: string, p: string) => cells.find((x) => x.country === c && x.product === p);
  const total = (p: string) =>
    cells.filter((x) => x.product === p).reduce((s, x) => s + x.value_usd, 0);

  return (
    <div className="flex flex-col gap-3">
      <table
        className="w-full table-fixed border-separate border-spacing-0.5"
        data-testid="heatmap"
      >
        <caption className="sr-only">
          Confirmed purchase order value by country and product, last 12 months, with growth over
          the last 3 months
        </caption>
        <thead>
          <tr>
            <th scope="col" className="w-28" />
            {PRODUCTS.map((p) => (
              <th
                key={p}
                scope="col"
                className="pb-1 text-left text-xs font-medium text-muted-foreground"
              >
                {PRODUCT_LABELS[p]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c}>
              <th scope="row" className="pr-3 text-left text-sm font-medium">
                {countryName(c)}
              </th>
              {PRODUCTS.map((p) => {
                const cell = at(c, p);
                if (!cell) return <td key={p} className="h-16 rounded-md bg-muted" />;
                const s = step(cell.value_usd, max);
                const light = s >= DARK_TEXT_FROM;
                return (
                  <td key={p} className="p-0">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          data-testid="heat-cell"
                          data-cell={`${c}-${p}`}
                          className="flex h-16 w-full flex-col justify-between rounded-md px-3 py-2 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/60"
                          style={{
                            backgroundColor: RAMP[s],
                            color: light ? "#ffffff" : "#0b0b0b",
                          }}
                        >
                          <span className="text-sm font-semibold tabular-nums">
                            {usdShort(cell.value_usd)}
                          </span>
                          <span className="flex items-center gap-0.5 text-xs tabular-nums opacity-90">
                            <GrowthMark value={cell.growth_pct} />
                            {signedPct(cell.growth_pct)}
                          </span>
                        </button>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs text-left leading-relaxed">
                        <span>
                          <strong className="font-semibold">
                            {countryName(c)}, {PRODUCT_LABELS[p]}
                          </strong>
                          <br />
                          {usdFull(cell.value_usd)} of confirmed POs in 12 months.
                          <br />
                          Last 3 months vs the 3 before: {signedPct(cell.growth_pct)}.
                          <br />
                          {cell.customers} {cell.customers === 1 ? "customer" : "customers"}.
                        </span>
                      </TooltipContent>
                    </Tooltip>
                  </td>
                );
              })}
            </tr>
          ))}
          {!country && (
            <tr>
              <th
                scope="row"
                className="pt-1 pr-3 text-left text-xs font-medium text-muted-foreground"
              >
                Region
              </th>
              {PRODUCTS.map((p) => (
                <td key={p} className="px-3 pt-1 text-xs text-muted-foreground tabular-nums">
                  {usdShort(total(p))}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
      <div className="flex items-center gap-3 text-xs text-muted-foreground" aria-hidden>
        <span>Less</span>
        <span className="flex h-2 w-40 overflow-hidden rounded-full">
          {RAMP.map((c) => (
            <span key={c} className="flex-1" style={{ backgroundColor: c }} />
          ))}
        </span>
        <span>More sales</span>
        <span className="ml-auto">
          Arrow and % = last 3 months vs the 3 before. Hover a cell for customers.
        </span>
      </div>
    </div>
  );
}
