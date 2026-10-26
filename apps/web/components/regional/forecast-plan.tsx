"use client";

import { MetricInfo } from "@/components/analytics/metric-info";
import { captionOf, PRODUCT_LABELS, type Captions } from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";

type Plan = Schema<"ForecastPlan">;
type Row = Schema<"PlanRow">;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthName(iso: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(iso);
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : iso;
}

/** Equipment counts are small (one decimal helps); test kits run in the thousands. */
function units(v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  return v < 100
    ? v.toLocaleString("en-US", { maximumFractionDigits: 1 })
    : Math.round(v).toLocaleString("en-US");
}

/**
 * Session 13: the equipment plan built from purchase requests (one plain line, its backtest
 * result) and the "Next 3 months plan" per country x product. The growth adjustment is its
 * own column and is never added into another one.
 */
export function ForecastPlanBlock({ note, plan }: { note: string | null; plan: Plan | null }) {
  if (!note && !plan) return null;
  const caps: Captions = plan?.captions ?? {};
  const cap = (key: string, title: string, caption: string) =>
    captionOf(caps, key, { title, caption });
  const excelCap = cap("excel_6m", "Excel 6-month", "3 x the average of the last 6 months.");
  const oursCap = cap("combination", "Ours", "Three statistical forecasts averaged.");
  const pipeCap = cap("pipeline_pr", "From requests", "Equipment only: requests x conversion.");
  const adjCap = cap("growth_adjustment", "Growth adjustment", "Fast-growing markets only.");
  const adjNotes = Array.from(
    new Map(
      (plan?.rows ?? [])
        .filter((r) => r.growth_adjustment_caption)
        .map((r) => [r.country, r.growth_adjustment_caption as string]),
    ).values(),
  );
  const span =
    plan && plan.months.length
      ? `${monthName(plan.months[0]!)} to ${monthName(plan.months[plan.months.length - 1]!)}`
      : "";

  return (
    <div className="flex max-w-4xl flex-col gap-3" data-testid="plan-block">
      {note && (
        <p className="text-sm leading-relaxed" data-testid="pipeline-note">
          <span className="font-medium">Planning equipment from requests: </span>
          {note}
        </p>
      )}
      {plan && (
        <>
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium">Next 3 months plan ({span}), units</p>
            <p className="text-xs text-muted-foreground">
              Units to plan per country and product, from the confirmed orders up to the end of{" "}
              {monthName(plan.origin)}. The columns sit side by side so you can compare them; none
              is added into another.
            </p>
          </div>
          <table className="w-full text-sm" data-testid="plan-table">
            <caption className="sr-only">
              Next 3 months plan: units per country and product for each planning method
            </caption>
            <thead>
              <tr className="text-xs text-muted-foreground">
                <th scope="col" className="pb-1 text-left font-normal">
                  Country
                </th>
                <th scope="col" className="pb-1 text-left font-normal">
                  Product
                </th>
                <th scope="col" className="pb-1 text-right font-normal">
                  <span className="inline-flex items-center gap-1">
                    Excel 6-month <MetricInfo caption={excelCap} />
                  </span>
                </th>
                <th scope="col" className="pb-1 text-right font-normal">
                  <span className="inline-flex items-center gap-1">
                    Ours <MetricInfo caption={oursCap} />
                  </span>
                </th>
                <th scope="col" className="pb-1 text-right font-normal">
                  <span className="inline-flex items-center gap-1">
                    From requests (equipment) <MetricInfo caption={pipeCap} />
                  </span>
                </th>
                <th scope="col" className="pb-1 text-right font-normal">
                  <span className="inline-flex items-center gap-1">
                    Growth adjustment (separate) <MetricInfo caption={adjCap} />
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {plan.rows.map((r: Row) => (
                <tr
                  key={`${r.country}-${r.product}`}
                  className="border-t"
                  data-testid={`plan-row-${r.country}-${r.product}`}
                >
                  <th scope="row" className="py-1 text-left font-normal">
                    {r.product === "A" ? r.country_name : ""}
                    <span className="sr-only">{r.product === "A" ? "" : r.country_name}</span>
                  </th>
                  <td className="py-1">{PRODUCT_LABELS[r.product] ?? r.product}</td>
                  <td className="py-1 text-right tabular-nums">{units(r.excel_6m)}</td>
                  <td className="py-1 text-right tabular-nums">{units(r.combination)}</td>
                  <td className="py-1 text-right tabular-nums">{units(r.pipeline_pr)}</td>
                  <td
                    className="py-1 text-right tabular-nums"
                    data-testid={r.growth_adjustment !== null ? "plan-adjustment" : undefined}
                  >
                    {r.growth_adjustment !== null && r.growth_adjustment !== undefined
                      ? `+${units(r.growth_adjustment)} (Excel ${Math.round(r.growth_adjustment_pct ?? 0)}% low)`
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
            {adjNotes.map((n) => (
              <li key={n} data-testid="plan-adjustment-note">
                <span className="font-medium text-foreground">Growth adjustment: </span>
                {n}
              </li>
            ))}
            {adjNotes.length === 0 && (
              <li data-testid="plan-adjustment-note">
                No market in this scenario grew fast enough to need a growth adjustment.
              </li>
            )}
            <li>
              From requests: test data favours this method; a pilot must measure the real
              conversion rate first.
            </li>
          </ul>
        </>
      )}
    </div>
  );
}
