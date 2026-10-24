import type { ReactNode } from "react";

import { SectionHeading } from "@/components/analytics/metric-info";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { captionOf, usdFull, usdShort } from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";
import { countryName } from "@/lib/format";

type View = Schema<"RegionalView">;

/**
 * PRD S1: the real accounts to act on, after merge. Before merge a customer split across SAP
 * records looks like it is fading or missing a product line when another record is still
 * ordering, so the lists are only shown once duplicates are linked.
 */
export function AccountLists({ data }: { data: View }) {
  if (data.view === "before") {
    return (
      <p
        className="rounded-xl border border-dashed px-4 py-3 text-sm text-muted-foreground"
        data-testid="account-lists-before"
      >
        Merge duplicates to see which real accounts are at risk.
      </p>
    );
  }
  const captions = data.captions;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-10">
      <AccountTable
        id="drop-off-title"
        testId="drop-off-list"
        caption={captionOf(captions, "drop_off_risk", {
          title: "At risk of dropping off",
          caption:
            "Regular customers who spent half or less in the last 3 months than in the same 3 months last year.",
        })}
        note="US$ = how much less they ordered in the last 3 months than in the same 3 months last year."
        total={data.drop_off_total?.caption}
        valueHeader="Ordered less"
        empty="No regular customer has cut their orders by half or more against the same quarter last year."
        rows={(data.drop_off_risk ?? []).map((r) => ({
          key: r.card_code,
          name: r.name,
          country: r.country,
          value: r.value_at_risk_usd,
          reason: r.reason,
        }))}
      />
      <AccountTable
        id="whitespace-title"
        testId="whitespace-list"
        caption={captionOf(captions, "cross_sell_whitespace", {
          title: "Cross-sell whitespace",
          caption: "Customers missing test kits or services that similar customers buy.",
        })}
        note="US$ = what similar customers in the same country typically spend a year on the missing product. An estimate."
        total={data.whitespace_total?.caption}
        valueHeader="Est. a year"
        empty="Every active customer already buys the products similar customers buy."
        rows={(data.cross_sell_whitespace ?? []).map((r) => ({
          key: r.card_code,
          name: r.name,
          country: r.country,
          value: r.est_value_usd,
          reason: r.reason,
          lowConfidence: r.low_confidence,
        }))}
      />
    </div>
  );
}

type Row = {
  key: string;
  name: string;
  country: string;
  value: number;
  reason: string;
  /** Whitespace only: under 10 comparable customers, left out of the US$ total. */
  lowConfidence?: boolean;
};

function AccountTable({
  id,
  testId,
  caption,
  note,
  total,
  valueHeader,
  empty,
  rows,
}: {
  id: string;
  testId: string;
  caption: Schema<"Caption">;
  note: ReactNode;
  total?: string;
  valueHeader: string;
  empty: string;
  rows: Row[];
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3" data-testid={testId}>
      <SectionHeading id={id} caption={caption} />
      <p className="text-xs text-muted-foreground">{note}</p>
      <div className="overflow-hidden rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                Customer
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                {valueHeader}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((r) => (
              <tr key={r.key} data-testid="account-row" className="align-top">
                <td className="px-3 py-2.5">
                  <div className="flex flex-col gap-0.5">
                    <span className="font-medium">{r.name}</span>
                    {r.lowConfidence && (
                      <Badge
                        variant="outline"
                        className="text-muted-foreground"
                        data-testid="low-confidence-marker"
                      >
                        Low confidence (fewer than 10 similar customers)
                      </Badge>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {countryName(r.country)}. {r.reason}
                    </span>
                  </div>
                </td>
                <td
                  className={cn(
                    "px-3 py-2.5 text-right font-semibold whitespace-nowrap tabular-nums",
                    r.lowConfidence && "text-muted-foreground",
                  )}
                  title={usdFull(r.value) + (r.lowConfidence ? " (not counted in the total)" : "")}
                >
                  {usdShort(r.value)}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={2} className="px-3 py-6 text-muted-foreground">
                  {empty}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {total && (
        <p className="text-xs text-muted-foreground" data-testid={`${testId}-total`}>
          {total}
        </p>
      )}
    </section>
  );
}
