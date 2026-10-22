"use client";

import { useEffect, useState } from "react";

import { MetricInfo, SectionHeading } from "@/components/analytics/metric-info";
import { OpsImpactCompact } from "@/components/ops/ops-impact-card";
import { ActionsList } from "@/components/regional/actions-list";
import { BridgeChart } from "@/components/regional/bridge-chart";
import { ForecastPanel } from "@/components/regional/forecast-panel";
import { Heatmap } from "@/components/regional/heatmap";
import { LostCustomers } from "@/components/regional/lost-customers";
import { MergeStrip } from "@/components/regional/merge-strip";
import { SignalPanels } from "@/components/regional/signal-panels";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SEGMENT_ON } from "@/components/analytics/segmented";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { captionOf, pct } from "@/lib/analytics";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { countryName } from "@/lib/format";
import { cn } from "@/lib/utils";

type View = Schema<"RegionalView">;
type MergeView = View["view"];
type Country = NonNullable<View["country"]>;

const COUNTRIES: Country[] = ["SG", "MY", "ID", "VN", "TH"];

type Pair = { before: View; after: View };

function explain(e: unknown): string {
  if (isApiError(e)) return e.message;
  return "The regional numbers could not be loaded.";
}

export function RegionalView() {
  const [view, setView] = useState<MergeView>("before");
  const [country, setCountry] = useState<Country | null>(null);
  // Both views load together so the before/after toggle is instant during the demo.
  const [pairs, setPairs] = useState<Record<string, Pair>>({});
  const [error, setError] = useState<string | null>(null);
  const [forecast, setForecast] = useState<Schema<"ForecastSummary"> | null>(null);
  const [forecastError, setForecastError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const key = country ?? "ALL";
  const pair = pairs[key];

  useEffect(() => {
    if (pairs[key]) return;
    let current = true;
    const query = (v: MergeView) => (country ? { view: v, country } : { view: v });
    Promise.all([
      api.GET("/analytics/regional", { query: query("before") }),
      api.GET("/analytics/regional", { query: query("after") }),
    ]).then(
      ([before, after]) => {
        if (!current) return;
        setPairs((p) => ({ ...p, [key]: { before, after } }));
        setError(null);
      },
      (e: unknown) => current && setError(explain(e)),
    );
    return () => {
      current = false;
    };
  }, [key, country, pairs, attempt]);

  useEffect(() => {
    let current = true;
    api.GET("/analytics/forecast").then(
      (s) => current && setForecast(s),
      (e: unknown) => current && setForecastError(explain(e)),
    );
    return () => {
      current = false;
    };
  }, [attempt]);

  const data = pair ? pair[view] : null;
  const captions = data?.captions ?? pair?.before.captions;

  return (
    <div className="flex flex-col gap-10">
      <header className="flex flex-col gap-5">
        <div className="flex max-w-3xl flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Regional business view</h1>
          <p className="text-base text-muted-foreground">
            Sales by country and product, from confirmed purchase orders only. Switch between the
            raw SAP records and one record per customer to see what duplicates do to the numbers.
          </p>
          <p className="flex items-center gap-1.5 text-sm" data-testid="period">
            <span className="font-medium">{pair ? pair.before.period : "Last 12 full months"}</span>
            {captions && (
              <MetricInfo
                caption={captionOf(captions, "period", {
                  title: "Stated period",
                  caption: "The last 12 full months of confirmed purchase orders.",
                })}
              />
            )}
            <span className="text-muted-foreground">Synthetic data, values in US dollars.</span>
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-1.5">
            <ToggleGroup
              type="single"
              variant="outline"
              spacing={0}
              value={view}
              onValueChange={(v) => v && setView(v as MergeView)}
              aria-label="Before or after merging duplicate customers"
              data-testid="merge-toggle"
            >
              <ToggleGroupItem
                value="before"
                data-testid="view-before"
                className={cn(SEGMENT_ON, "px-4")}
              >
                Before merge: every SAP record
              </ToggleGroupItem>
              <ToggleGroupItem
                value="after"
                data-testid="view-after"
                className={cn(SEGMENT_ON, "px-4")}
              >
                After merge: one per customer
              </ToggleGroupItem>
            </ToggleGroup>
            {captions && (
              <MetricInfo
                caption={captionOf(captions, "view", {
                  title: "Before / after merge",
                  caption: "Before: every SAP record counts. After: linked duplicates count once.",
                })}
              />
            )}
          </div>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            spacing={0}
            value={country ?? "ALL"}
            onValueChange={(v) => v && setCountry(v === "ALL" ? null : (v as Country))}
            aria-label="Country"
            data-testid="country-filter"
          >
            <ToggleGroupItem value="ALL" className={SEGMENT_ON}>
              All five
            </ToggleGroupItem>
            {COUNTRIES.map((c) => (
              <ToggleGroupItem
                key={c}
                value={c}
                data-testid={`country-${c}`}
                className={SEGMENT_ON}
              >
                {countryName(c)}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
      </header>

      {error && !pair ? (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed p-6 text-sm">
          <p>{error}</p>
          <Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
        </div>
      ) : !pair || !data || !captions ? (
        <div className="flex flex-col gap-8" aria-busy>
          <Skeleton className="h-32 w-full" />
          <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] gap-10">
            <Skeleton className="h-96 w-full" />
            <Skeleton className="h-96 w-full" />
          </div>
          <Skeleton className="h-28 w-full" />
        </div>
      ) : (
        <>
          <MergeStrip pair={pair} view={view} country={country} />

          <div className="grid grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] gap-10">
            <section aria-labelledby="heatmap-title" className="flex flex-col gap-4">
              <SectionHeading
                id="heatmap-title"
                caption={captionOf(captions, "heatmap", {
                  title: "Sales by country and product",
                  caption: "Value of confirmed POs in the last 12 months, in US dollars.",
                })}
              />
              <Heatmap cells={data.heatmap} country={country} />
              <p className="text-xs text-muted-foreground">
                Merging duplicates does not change these totals: the same orders are grouped under
                fewer customers.
              </p>
            </section>

            <section aria-labelledby="growth-title" className="flex flex-col gap-5">
              <h2 id="growth-title" className="text-base font-semibold tracking-tight">
                Growth, last 3 months vs the 3 before
              </h2>
              <dl className="grid grid-cols-3 gap-4" data-testid="growth-kpis">
                <Kpi
                  testId="kpi-nrr"
                  value={pct(data.nrr_pct)}
                  label="of last period's spend kept by existing customers"
                  caption={captionOf(captions, "nrr_pct", {
                    title: "Net revenue retention",
                    caption: "Spend this period by last period's customers, as a % of before.",
                  })}
                />
                <Kpi
                  testId="kpi-cross-sell"
                  value={pct(data.cross_sell_pct)}
                  label="of customers buy 2 or more product lines"
                  caption={captionOf(captions, "cross_sell_pct", {
                    title: "Cross-sell penetration",
                    caption: "Share of active customers buying at least 2 of Products A, B and C.",
                  })}
                />
                <Kpi
                  testId="kpi-customers"
                  value={data.customer_count.toLocaleString("en-US")}
                  label={view === "before" ? "customer records ordered" : "customers ordered"}
                  caption={captionOf(captions, "customer_count", {
                    title: "Active customers",
                    caption: "Customers with at least one confirmed PO in the last 12 months.",
                  })}
                />
              </dl>
              {view === "before" && data.cross_sell_pct === 0 && (
                <p
                  className="-mt-2 border-l-2 border-warning pl-3 text-xs text-muted-foreground"
                  data-testid="cross-sell-note"
                >
                  <span className="font-medium text-foreground">Why cross-sell shows 0%: </span>
                  in this synthetic data each company keeps its own record of a customer and sells
                  one product line, so before merging no record buys two. 0% is expected.
                </p>
              )}
              <div className="flex flex-col gap-1">
                <p className="flex items-center gap-1 text-sm font-medium">
                  Revenue bridge
                  <MetricInfo
                    caption={captionOf(captions, "bridge", {
                      title: "Revenue bridge",
                      caption: "How the prior 3 months' revenue became the last 3 months'.",
                    })}
                  />
                </p>
                <p className="text-xs text-muted-foreground">
                  How the prior 3 months became the last 3: plus new customers and those who bought
                  more, minus those who bought less or stopped.
                </p>
              </div>
              <BridgeChart bridge={data.bridge} />
            </section>
          </div>

          <section aria-labelledby="panels-title" className="flex flex-col gap-4">
            <SectionHeading
              id="panels-title"
              caption={captionOf(captions, "panels", {
                title: "POs, enquiries and requests",
                caption: "Kept apart on purpose: only confirmed POs are demand.",
              })}
            />
            <SignalPanels panels={data.panels} />
          </section>

          <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-10">
            <LostCustomers
              view={view}
              lost={data.lost_customers}
              caption={captionOf(captions, "lost_customers", {
                title: "Lost-customer alerts",
                caption: "Customers with no PO for longer than usual.",
              })}
            />
            <ActionsList
              actions={data.actions}
              caption={captionOf(captions, "actions", {
                title: "Recommended actions",
                caption: "Generated from the numbers on this page by fixed rules, not by AI.",
              })}
            />
          </div>
        </>
      )}

      <hr />

      {forecast ? (
        <ForecastPanel summary={forecast} />
      ) : forecastError ? (
        <p className="text-sm text-muted-foreground">{forecastError}</p>
      ) : (
        <Skeleton className="h-96 w-full" aria-busy />
      )}

      <hr />

      <OpsImpactCompact />
    </div>
  );
}

function Kpi({
  value,
  label,
  caption,
  testId,
}: {
  value: string;
  label: string;
  caption: Schema<"Caption">;
  testId: string;
}) {
  return (
    <div className="flex flex-col gap-1" data-testid={testId}>
      <dt className="flex items-center gap-1 text-xs text-muted-foreground">
        {caption.title}
        <MetricInfo caption={caption} />
      </dt>
      <dd className="text-2xl font-semibold tabular-nums" data-testid={`${testId}-value`}>
        {value}
      </dd>
      <dd className="text-xs text-muted-foreground">{label}</dd>
    </div>
  );
}
