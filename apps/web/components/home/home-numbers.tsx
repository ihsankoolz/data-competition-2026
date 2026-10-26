"use client";

/**
 * The four numbers on the home page, each from the API (never typed in here): Amy's modelled
 * cycle time, the customer count and lost-customer alerts before vs after the merge, and the
 * 12-month sales total that the merge leaves unchanged.
 */
import { useEffect, useState } from "react";

import { MetricInfo } from "@/components/analytics/metric-info";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { captionOf, type Caption, days, usdShort } from "@/lib/analytics";
import { api, isApiError, type Schema } from "@/lib/api/client";

type Loaded<T> = { data: T | null; error: string | null; retry: () => void };

/** `load` must be a stable function (the module-level loaders below). */
function useLoad<T>(load: () => Promise<T>, what: string): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    load().then(
      (d) => {
        if (!current) return;
        setData(d);
        setError(null);
      },
      (e: unknown) => current && setError(isApiError(e) ? e.message : `${what} could not load.`),
    );
    return () => {
      current = false;
    };
  }, [load, what, attempt]);
  return { data, error, retry: () => setAttempt((n) => n + 1) };
}

const loadOps = () => api.GET("/analytics/ops-impact");
const loadMerge = () => api.GET("/analytics/merge-impact");
const loadRegional = () => api.GET("/analytics/regional", { query: { view: "after" } });

/** The 12-month confirmed-PO total: the sum of the heatmap, the same before and after merge. */
export function salesTotal(view: Schema<"RegionalView">): number {
  return view.heatmap.reduce((sum, c) => sum + c.value_usd, 0);
}

function Stat({
  testId,
  label,
  info,
  before,
  after,
  unit,
  caption,
}: {
  testId: string;
  label: string;
  info: Caption;
  before?: string;
  after: string;
  unit?: string;
  caption: string;
}) {
  return (
    <div className="flex flex-col gap-1.5 px-6 first:pl-0 last:pr-0" data-testid={testId}>
      <dt className="flex items-center gap-1 text-sm text-muted-foreground">
        {label}
        <MetricInfo caption={info} />
      </dt>
      <dd className="flex items-baseline gap-2 tabular-nums">
        {before !== undefined && (
          <>
            <span
              className="text-lg text-muted-foreground line-through decoration-1"
              data-testid={`${testId}-before`}
            >
              {before}
            </span>
            <span className="sr-only">became</span>
          </>
        )}
        <span className="text-3xl font-semibold tracking-tight" data-testid={`${testId}-after`}>
          {after}
        </span>
        {unit && <span className="text-sm text-muted-foreground">{unit}</span>}
      </dd>
      <dd className="text-xs leading-relaxed text-muted-foreground">{caption}</dd>
    </div>
  );
}

function Pending({ testId }: { testId: string }) {
  return (
    <div className="flex flex-col gap-2 px-6 first:pl-0 last:pr-0" aria-busy data-testid={testId}>
      <Skeleton className="h-5 w-40" />
      <Skeleton className="h-9 w-32" />
      <Skeleton className="h-8 w-full" />
    </div>
  );
}

export function HomeNumbers() {
  const ops = useLoad(loadOps, "The cycle-time numbers");
  const merge = useLoad(loadMerge, "The before and after merge numbers");
  const regional = useLoad(loadRegional, "The regional sales numbers");
  const failed = [ops, merge, regional].filter((l) => l.error && !l.data);

  if (failed.length > 0)
    return (
      <div
        className="flex flex-col items-start gap-3 rounded-xl border border-dashed p-6 text-sm"
        role="alert"
        data-testid="home-numbers-error"
      >
        <p>{failed[0]!.error}</p>
        <Button variant="outline" size="sm" onClick={() => failed.forEach((l) => l.retry())}>
          Try again
        </Button>
      </div>
    );

  const o = ops.data;
  const m = merge.data;
  const r = regional.data;
  const captions = r?.captions;

  return (
    <dl className="grid grid-cols-4 divide-x" data-testid="home-numbers">
      {o ? (
        <Stat
          testId="home-stat-amy"
          label="Amy's new test-kit item"
          info={{ title: "Modelled, not measured", caption: o.caption }}
          before={days(o.amy_before_bd)}
          after={`~${days(Math.round(o.amy_after_bd))}`}
          unit="business days"
          caption="Modelled, not measured: from request to live in SAP, with every approver deciding at the same time instead of one after another."
        />
      ) : (
        <Pending testId="home-stat-amy-loading" />
      )}
      {m && r ? (
        <Stat
          testId="home-stat-customers"
          label="Customers"
          info={captionOf(captions, "customer_count", {
            title: "Active customers",
            caption: "Customers with at least one confirmed PO in the last 12 months.",
          })}
          before={m.customers_before.toLocaleString("en-US")}
          after={m.customers_after.toLocaleString("en-US")}
          caption="Once duplicate records are linked, each hospital is counted once, not once per SAP record."
        />
      ) : (
        <Pending testId="home-stat-customers-loading" />
      )}
      {m && r ? (
        <Stat
          testId="home-stat-lost"
          label="Lost-customer alerts"
          info={captionOf(captions, "lost_customers", {
            title: "Lost-customer alerts",
            caption: "Customers with no confirmed PO for longer than usual.",
          })}
          before={String(m.lost_before)}
          after={String(m.lost_after)}
          caption={lostCaption(m.lost_that_were_duplicates, r.lost_alert_change.new_after_merge)}
        />
      ) : (
        <Pending testId="home-stat-lost-loading" />
      )}
      {r ? (
        <Stat
          testId="home-stat-sales"
          label="Sales from confirmed orders"
          info={captionOf(captions, "heatmap", {
            title: "Sales by country and product",
            caption: "Value of confirmed POs in the last 12 months, in US dollars.",
          })}
          after={usdShort(salesTotal(r))}
          caption={`${r.period}. The same before and after the merge: it fixes who the customer is, not how much was sold.`}
        />
      ) : (
        <Pending testId="home-stat-sales-loading" />
      )}
    </dl>
  );
}

/** "30 were false alarms: ... 2 more are caught once their records are combined." */
export function lostCaption(falseAlarms: number, newlyCaught: number): string {
  const gone =
    falseAlarms === 1
      ? "1 was a false alarm: a customer still ordering under another record."
      : `${falseAlarms} were false alarms: customers still ordering under another record.`;
  if (newlyCaught === 0) return gone;
  return `${gone} ${newlyCaught} more ${newlyCaught === 1 ? "is" : "are"} caught once their records are combined.`;
}
