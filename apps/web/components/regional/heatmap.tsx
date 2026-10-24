"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { MetricInfo } from "@/components/analytics/metric-info";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  captionOf,
  type Captions,
  PRODUCT_LABELS,
  signedPct,
  usdFull,
  usdShort,
} from "@/lib/analytics";
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
// Steps from here on carry white text: white on L 0.51 is above 4.5:1, on the darkest step about
// 9:1. Below it, near-black text wins (on L 0.57 black is about 4.9:1, white only 4.3:1).
const DARK_TEXT_FROM = 9;
const TEXT_ON_DARK = "oklch(1 0 0)";
const TEXT_ON_LIGHT = "oklch(0.15 0 0)";

/** Product B (equipment) sells in a few large orders, so its growth swings (D-022 #3). */
const LUMPY = "B";
const LUMPY_MARK = "Lumpy: plan from the enquiry pipeline";

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

function LumpyTag({ testId }: { testId?: string }) {
  return (
    <span
      className="shrink-0 rounded-sm border border-current/40 px-1 text-[10px] leading-4 font-medium"
      data-testid={testId}
    >
      Lumpy
    </span>
  );
}

export function Heatmap({
  cells,
  country,
  captions,
}: {
  cells: HeatCell[];
  country: string | null;
  captions: Captions;
}) {
  // Each cell's growth is the 12-month headline measure (D-022 #3), not the 3-month change.
  const growthCap = captionOf(captions, "growth_12m_pct", {
    title: "Growth (12 months)",
    caption: "Sales in the last 12 months compared with the 12 months before, as a % change.",
  });
  const lumpyCap = captionOf(captions, "product_b_note", {
    title: "Product B is lumpy",
    caption:
      "Equipment sells in a few large orders, so its growth swings from quarter to quarter. " +
      "Plan it from the enquiry pipeline, not from past growth.",
  });
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
          Confirmed purchase order value by country and product, last 12 months, with growth: last
          12 months vs the 12 before
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
                const lumpy = p === LUMPY;
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
                            color: light ? TEXT_ON_DARK : TEXT_ON_LIGHT,
                          }}
                        >
                          <span className="flex items-start justify-between gap-2">
                            <span className="text-sm font-semibold tabular-nums">
                              {usdShort(cell.value_usd)}
                            </span>
                            {lumpy && <LumpyTag testId="lumpy-marker" />}
                          </span>
                          <span
                            className="flex items-center gap-0.5 text-xs tabular-nums opacity-90"
                            data-testid="heat-growth"
                          >
                            <GrowthMark value={cell.growth_12m_pct} />
                            {signedPct(cell.growth_12m_pct)}
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
                          Growth, last 12 months vs the 12 before: {signedPct(cell.growth_12m_pct)}.
                          <br />
                          {cell.customers} {cell.customers === 1 ? "customer" : "customers"}.
                          {lumpy && (
                            <>
                              <br />
                              <strong className="font-semibold">{LUMPY_MARK}.</strong>{" "}
                              {lumpyCap.caption}
                            </>
                          )}
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
      <div className="flex flex-col gap-1.5 text-xs text-muted-foreground">
        <div className="flex items-center gap-3 whitespace-nowrap">
          <span className="flex items-center gap-3" aria-hidden>
            <span>Less</span>
            <span className="flex h-2 w-32 overflow-hidden rounded-full">
              {RAMP.map((c) => (
                <span key={c} className="flex-1" style={{ backgroundColor: c }} />
              ))}
            </span>
            <span>More sales</span>
          </span>
          <span className="ml-auto">Hover a cell for its customers.</span>
        </div>
        <p className="flex items-center gap-1" data-testid="heat-growth-caption">
          Arrow and %: {growthCap.title.toLowerCase()}, the last 12 months vs the 12 before.
          <MetricInfo caption={growthCap} />
        </p>
        <p className="flex items-center gap-1.5" data-testid="lumpy-note">
          <LumpyTag />
          {LUMPY_MARK}.
          <MetricInfo caption={lumpyCap} />
        </p>
      </div>
    </div>
  );
}
