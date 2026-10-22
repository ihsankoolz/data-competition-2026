"use client";

import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

import { MetricInfo } from "@/components/analytics/metric-info";
import { SEGMENT_ON } from "@/components/analytics/segmented";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  captionOf,
  PRODUCT_LABELS,
  pct,
  SCENARIO_LABELS,
  signedPct,
  type Captions,
} from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";
import { countryName } from "@/lib/format";

type Summary = Schema<"ForecastSummary">;
type Run = Schema<"ForecastBacktest">;
type Score = Schema<"ForecastScore">;
type DataKind = Run["data"];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthLabel(iso: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(iso);
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1].slice(2)}` : iso;
}

function score(scores: Score[] | undefined, method: Score["method"]): Score | undefined {
  return scores?.find((s) => s.method === method);
}

function biasText(s: Score | undefined): string {
  return s ? signedPct(s.bias_pct) : "not scored";
}

function productScores(run: Run | undefined, product: string): Score[] | undefined {
  return run?.series.find((s) => s.level === "product" && s.product === product)?.scores;
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number | null; color?: string }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-sm">
      <p className="mb-1 font-medium">{label ? monthLabel(label) : ""}</p>
      {payload
        .filter((p) => p.value !== null && p.value !== undefined)
        .map((p) => (
          <p key={p.name} className="flex items-center gap-2 tabular-nums">
            <span className="size-2 rounded-full" style={{ backgroundColor: p.color }} />
            {p.name}: {Math.round(Number(p.value)).toLocaleString("en-US")} units
          </p>
        ))}
    </div>
  );
}

export function ForecastPanel({ summary }: { summary: Summary }) {
  const captions: Captions = summary.captions;
  const scenarios = Array.from(new Set(summary.runs.map((r) => r.scenario)));
  const [scenario, setScenario] = useState<Run["scenario"]>(
    scenarios.includes("seasonal_trend") ? "seasonal_trend" : (scenarios[0] ?? "seasonal_trend"),
  );
  const [data, setData] = useState<DataKind>("clean");
  const find = (d: DataKind) => summary.runs.find((r) => r.scenario === scenario && r.data === d);
  const run = find(data);
  const clean = find("clean");
  const dirty = find("dirty");

  const wapeCap = captionOf(captions, "wape_pct", {
    title: "Forecast error",
    caption: "How far off the forecast was, as a % of the units actually ordered.",
  });
  const biasCap = captionOf(captions, "bias_pct", {
    title: "Bias",
    caption: "Whether the forecast ran high (+) or low (-).",
  });
  const cleanDirtyCap = captionOf(captions, "clean_dirty", {
    title: "Clean vs dirty data",
    caption: "Dirty = enquiries and requests counted as orders. Clean = confirmed POs only.",
  });
  const scenarioCap = captionOf(captions, "scenarios", {
    title: "Scenarios",
    caption: "Three synthetic markets.",
  });

  const bClean = score(productScores(clean, "B"), "excel_6m");
  const bDirty = score(productScores(dirty, "B"), "excel_6m");
  const excel = score(run?.overall, "excel_6m");
  const excel12 = score(run?.overall, "excel_12m");
  const ours = score(run?.overall, "combination");

  const bias = run?.bias_by_country ?? [];
  const biasRows = bias.some((b) => !b.product) ? bias.filter((b) => !b.product) : bias;

  return (
    <section
      aria-labelledby="forecast-title"
      className="flex flex-col gap-6"
      data-testid="forecast-panel"
    >
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex max-w-2xl flex-col gap-1">
          <h2 id="forecast-title" className="text-xl font-semibold tracking-tight">
            Forecast check: the biggest error is the data, not the model
          </h2>
          <p className="text-sm text-muted-foreground">
            We replayed the last 12 months: each month, today&apos;s Excel average and our method
            forecast the next 3 months from the data available then, and we compared with what
            customers really ordered. Synthetic data.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-1.5">
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              spacing={0}
              value={scenario}
              onValueChange={(v) => v && setScenario(v as Run["scenario"])}
              aria-label="Market scenario"
            >
              {scenarios.map((s) => (
                <ToggleGroupItem
                  key={s}
                  value={s}
                  data-testid={`scenario-${s}`}
                  className={SEGMENT_ON}
                >
                  {SCENARIO_LABELS[s] ?? s}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <MetricInfo caption={scenarioCap} />
          </div>
          <div className="flex items-center gap-1.5">
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              spacing={0}
              value={data}
              onValueChange={(v) => v && setData(v as DataKind)}
              aria-label="Which order data"
            >
              <ToggleGroupItem value="clean" data-testid="data-clean" className={SEGMENT_ON}>
                Confirmed POs only
              </ToggleGroupItem>
              <ToggleGroupItem value="dirty" data-testid="data-dirty" className={SEGMENT_ON}>
                Today&apos;s spreadsheet
              </ToggleGroupItem>
            </ToggleGroup>
            <MetricInfo caption={cleanDirtyCap} />
          </div>
        </div>
      </div>

      {bClean && bDirty && (
        <div
          className="flex flex-wrap items-baseline gap-x-6 gap-y-2 border-l-4 border-viz-loss bg-muted/40 py-3 pr-4 pl-5"
          data-testid="data-headline"
        >
          <p className="text-sm">
            <span className="font-semibold">Equipment (Product B):</span> the Excel plan misses by{" "}
            <span className="font-semibold tabular-nums">{pct(bClean.wape_pct, 0)}</span> of volume
            on confirmed orders, and by{" "}
            <span className="font-semibold tabular-nums">{pct(bDirty.wape_pct, 0)}</span> when
            enquiries and requests leak into the spreadsheet as orders. Cleaning the data does more
            than changing the model.
          </p>
        </div>
      )}

      {run ? (
        <div className="grid grid-cols-[minmax(0,1fr)_20rem] gap-8">
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">
              {run.chart_series}: actual orders vs each forecast
            </p>
            <LineChart
              data={run.chart}
              responsive
              style={{ width: "100%", height: 260 }}
              margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
              accessibilityLayer
            >
              <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
              <XAxis
                dataKey="month"
                tickFormatter={monthLabel}
                tickLine={false}
                axisLine={{ stroke: "var(--viz-grid)" }}
                tick={{ fontSize: 11, fill: "var(--viz-axis)" }}
                minTickGap={24}
              />
              <YAxis
                width={48}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11, fill: "var(--viz-axis)" }}
                tickFormatter={(v: number) => v.toLocaleString("en-US")}
              />
              <Tooltip content={<ChartTooltip />} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
              <Line
                name="Actual orders"
                dataKey="actual"
                stroke="var(--viz-ink)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                name="Excel average (6 months)"
                dataKey="excel_6m"
                stroke="var(--viz-excel)"
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
              <Line
                name="Our method"
                dataKey="combination"
                stroke="var(--viz-accent)"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
            <p className="text-xs text-muted-foreground">{run.setup}</p>
          </div>

          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-1" data-testid="overall-scores">
              <p className="flex items-center gap-1 text-sm font-medium">
                All 15 country and product forecasts <MetricInfo caption={wapeCap} />
              </p>
              {ours && excel && (
                <p className="text-2xl font-semibold tabular-nums" data-testid="overall-ours">
                  {pct(ours.wape_pct)}
                </p>
              )}
              {ours && excel && (
                <p className="text-sm text-muted-foreground">
                  Forecast error with our method, as a share of volume. Excel 6-month average:{" "}
                  <span
                    className="font-medium text-foreground tabular-nums"
                    data-testid="overall-excel"
                  >
                    {pct(excel.wape_pct)}
                  </span>
                  {excel12 ? `; 12-month: ${pct(excel12.wape_pct)}` : ""}.
                </p>
              )}
              {ours && excel && (
                <p className="flex items-center gap-1 text-xs text-muted-foreground">
                  Ours ran {ours.bias_pct >= 0 ? "high" : "low"} by {pct(Math.abs(ours.bias_pct))};
                  Excel ran {excel.bias_pct >= 0 ? "high" : "low"} by{" "}
                  {pct(Math.abs(excel.bias_pct))}. <MetricInfo caption={biasCap} />
                </p>
              )}
            </div>
            <table className="w-full text-sm" data-testid="product-scores">
              <caption className="pb-2 text-left text-sm font-medium">
                Error for the whole region, by product
              </caption>
              <thead>
                <tr className="text-xs text-muted-foreground">
                  <th scope="col" className="pb-1 text-left font-normal">
                    Product
                  </th>
                  <th scope="col" className="pb-1 text-right font-normal">
                    Excel 6-month
                  </th>
                  <th scope="col" className="pb-1 text-right font-normal">
                    Ours
                  </th>
                </tr>
              </thead>
              <tbody>
                {["A", "B", "C"].map((p) => {
                  const sc = productScores(run, p);
                  const e = score(sc, "excel_6m");
                  const o = score(sc, "combination");
                  if (!e || !o) return null;
                  return (
                    <tr key={p} className="border-t" data-testid={`product-row-${p}`}>
                      <th scope="row" className="py-1.5 text-left font-normal">
                        {PRODUCT_LABELS[p]}
                      </th>
                      <td
                        className={`py-1.5 text-right tabular-nums ${e.wape_pct <= o.wape_pct ? "font-semibold" : ""}`}
                      >
                        {pct(e.wape_pct)}
                      </td>
                      <td
                        className={`py-1.5 text-right tabular-nums ${o.wape_pct < e.wape_pct ? "font-semibold" : ""}`}
                      >
                        {pct(o.wape_pct)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="text-xs text-muted-foreground">Bold = the smaller error.</p>
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No backtest for this scenario yet.</p>
      )}

      {run && (
        <p className="max-w-3xl text-sm leading-relaxed" data-testid="honest-note">
          <span className="font-medium">In plain words: </span>
          {run.honest_note}
        </p>
      )}

      {biasRows.length > 0 && (
        <table className="w-full max-w-3xl text-sm" data-testid="bias-table">
          <caption className="pb-2 text-left">
            <span className="block font-medium">
              Does the Excel average fall behind growing markets?
            </span>
            {run?.bias_note && <span className="block text-muted-foreground">{run.bias_note}</span>}
          </caption>
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th scope="col" className="pb-1 text-left font-normal">
                Country
              </th>
              {biasRows.some((b) => b.product) && (
                <th scope="col" className="pb-1 text-left font-normal">
                  Product
                </th>
              )}
              <th scope="col" className="pb-1 text-right font-normal">
                Market growth (units, year on year)
              </th>
              <th scope="col" className="pb-1 text-right font-normal">
                Excel 6-month ran high (+) or low (-)
              </th>
              <th scope="col" className="pb-1 text-right font-normal">
                Ours ran high (+) or low (-)
              </th>
            </tr>
          </thead>
          <tbody>
            {biasRows.map((b) => (
              <tr key={`${b.country}-${b.product ?? "all"}`} className="border-t">
                <th scope="row" className="py-1.5 text-left font-normal">
                  {countryName(b.country)}
                </th>
                {biasRows.some((x) => x.product) && (
                  <td className="py-1.5">{b.product ? PRODUCT_LABELS[b.product] : "All"}</td>
                )}
                <td className="py-1.5 text-right tabular-nums">{signedPct(b.growth_pct)}</td>
                <td className="py-1.5 text-right tabular-nums">
                  {biasText(score(b.scores, "excel_6m"))}
                </td>
                <td className="py-1.5 text-right tabular-nums">
                  {biasText(score(b.scores, "combination"))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
