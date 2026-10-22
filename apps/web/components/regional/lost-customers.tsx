"use client";

import { Copy } from "lucide-react";

import { SectionHeading } from "@/components/analytics/metric-info";
import { Badge } from "@/components/ui/badge";
import type { Caption } from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";
import { countryName, formatDay } from "@/lib/format";

type Lost = Schema<"LostCustomer">;

export function LostCustomers({
  lost,
  view,
  caption,
}: {
  lost: Lost[];
  view: "before" | "after";
  caption: Caption;
}) {
  const dupes = lost.filter((l) => l.is_duplicate_artefact).length;
  // Duplicates first in the before view, so the false alarms are what the eye lands on.
  const sorted = [...lost].sort(
    (a, b) =>
      Number(b.is_duplicate_artefact) - Number(a.is_duplicate_artefact) ||
      a.last_order.localeCompare(b.last_order),
  );

  return (
    <section
      aria-labelledby="lost-title"
      className="flex flex-col gap-4"
      data-testid="lost-customers"
    >
      <SectionHeading id="lost-title" caption={caption} />
      <p className="text-sm" data-testid="lost-count">
        <span className="font-semibold tabular-nums">{lost.length}</span>{" "}
        {lost.length === 1 ? "alert" : "alerts"}
        {view === "before" && dupes > 0 && (
          <>
            , of which <span className="font-semibold tabular-nums">{dupes}</span> are really
            duplicates of a customer that is still ordering
          </>
        )}
        {view === "after" && <>, each a real customer that has gone quiet</>}.
      </p>
      <ul className="flex max-h-[26rem] flex-col divide-y overflow-y-auto rounded-xl border">
        {sorted.map((l) => (
          <li
            key={l.card_code}
            className="flex items-center justify-between gap-3 px-4 py-2.5"
            data-testid="lost-row"
            data-duplicate={l.is_duplicate_artefact ? "true" : "false"}
          >
            <div className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-medium">{l.name}</span>
              <span className="text-xs text-muted-foreground">
                {countryName(l.country)}, last order {formatDay(l.last_order)}
              </span>
            </div>
            <span
              className="ml-auto shrink-0 text-xs text-muted-foreground/80 tabular-nums"
              title={view === "after" ? "Merged customer ID" : "SAP record"}
            >
              {l.card_code}
            </span>
            {l.is_duplicate_artefact && (
              <Badge
                variant="secondary"
                className="bg-warning/15 text-warning-foreground"
                data-testid="duplicate-marker"
              >
                <Copy aria-hidden />
                Really a duplicate
              </Badge>
            )}
          </li>
        ))}
        {sorted.length === 0 && (
          <li className="px-4 py-6 text-sm text-muted-foreground">
            No customer has gone quiet for longer than usual.
          </li>
        )}
      </ul>
    </section>
  );
}
