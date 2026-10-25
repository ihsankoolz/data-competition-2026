"use client";

import { ArrowRight } from "lucide-react";

import { MetricInfo } from "@/components/analytics/metric-info";
import { type Caption, pct } from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";
import { countryName } from "@/lib/format";
import { cn } from "@/lib/utils";

type View = Schema<"RegionalView">;

type Moving = {
  key: string;
  label: string;
  before: string;
  after: string;
  note: string;
  info?: Caption;
};

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * The demo beat: what merging duplicate customers changes. Numbers come from the two views
 * the page already holds, so they follow the country filter.
 */
export function MergeStrip({
  pair,
  view,
  country,
}: {
  pair: { before: View; after: View };
  view: View["view"];
  country: string | null;
}) {
  const { before, after } = pair;
  const lostBefore = before.lost_customers.length;
  const dupes = before.lost_customers.filter((l) => l.is_duplicate_artefact).length;
  const where = country ? `in ${countryName(country)}` : "in the region";
  // After merge, say how the alert count moved (from the API, so it follows the filter):
  // before - false alarms + newly caught = after. Nothing moved: keep the general caption.
  const lc = after.lost_alert_change;
  const lostMoved = view === "after" && (lc.duplicates > 0 || lc.new_after_merge > 0);
  const lostNote = lostMoved
    ? [
        lc.duplicates > 0 && `${plural(lc.duplicates, "false alarm", "false alarms")} gone`,
        lc.new_after_merge > 0 && `${lc.new_after_merge} newly caught`,
      ]
        .filter(Boolean)
        .join(", ")
    : "false alarms from old or copied records disappear";

  const moving: Moving[] = [
    {
      key: "customers",
      label: "Active customers",
      before: before.customer_count.toLocaleString("en-US"),
      after: after.customer_count.toLocaleString("en-US"),
      note: "the same hospital counted once, not once per company",
    },
    {
      key: "lost",
      label: "Lost-customer alerts",
      before: String(lostBefore),
      after: String(after.lost_customers.length),
      note: lostNote,
      info:
        lostMoved && lc.new_after_merge > 0 ? after.captions.lost_new_after_merge : undefined,
    },
    {
      key: "nrr",
      label: "Revenue kept from existing customers",
      before: pct(before.nrr_pct),
      after: pct(after.nrr_pct),
      note: "customers who moved records no longer look lost",
    },
    {
      key: "cross",
      label: "Customers buying 2+ product lines",
      before: pct(before.cross_sell_pct, 0),
      after: pct(after.cross_sell_pct, 0),
      note: "each company's copy only ever saw its own product",
    },
  ];

  return (
    <section
      aria-labelledby="merge-title"
      className="flex flex-col gap-5 rounded-xl border bg-muted/30 px-6 py-5"
      data-testid="merge-strip"
    >
      <div className="flex flex-col gap-1">
        <h2
          id="merge-title"
          className="text-xl font-semibold tracking-tight"
          data-testid="merge-headline"
        >
          {dupes} of {lostBefore} &lsquo;lost customer&rsquo; alerts {where} were really duplicates
        </h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          They are customers still ordering under another SAP record. Our duplicate check links them
          (a person confirms every link), and the alerts go away. Total sales do not change.
        </p>
      </div>
      <dl className="grid grid-cols-4 gap-6">
        {moving.map((m) => (
          <div key={m.key} className="flex flex-col gap-1" data-testid={`moving-${m.key}`}>
            <dt className="text-xs text-muted-foreground">{m.label}</dt>
            <dd className="flex items-baseline gap-2 tabular-nums">
              <span
                className={cn(
                  "text-lg transition-colors",
                  view === "before"
                    ? "font-semibold text-foreground"
                    : "text-muted-foreground line-through decoration-1",
                )}
              >
                {m.before}
              </span>
              <ArrowRight
                className="size-3.5 self-center text-muted-foreground"
                role="img"
                aria-label="becomes"
              />
              <span
                className={cn(
                  "text-lg transition-colors",
                  view === "after" ? "font-semibold text-viz-accent" : "text-muted-foreground",
                )}
              >
                {m.after}
              </span>
            </dd>
            <dd
              className="flex items-center gap-0.5 text-xs text-muted-foreground"
              data-testid={`moving-${m.key}-note`}
            >
              {m.note}
              {m.info && <MetricInfo caption={m.info} />}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
