import { Check, CircleCheck, CircleDashed, TriangleAlert, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { Schema } from "@/lib/api/client";
import { formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";

type SapPublishView = Schema<"SapPublishView">;

const RESOURCE_TEXT: Record<SapPublishView["resource"], string> = {
  BusinessPartners: "Business partner",
  Items: "Item",
  ProfitCenters: "Cost Center",
};

/** Shown when the request is published but the read-back details have not reached this build. */
export function ReadbackUnavailable() {
  return (
    <div
      className="flex items-start gap-3 rounded-xl border border-dashed p-4 text-sm"
      data-testid="readback-unavailable"
    >
      <CircleDashed className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <p className="text-muted-foreground">
        Read-back details are not available yet. The record was sent to SAP; the field-by-field
        check will show here once the server provides it.
      </p>
    </div>
  );
}

/**
 * What we sent to SAP Business One next to what SAP saved, field by field.
 * Bank values arrive masked from the API.
 */
export function SapReadback({ view }: { view: SapPublishView }) {
  const mismatches = view.rows.filter((r) => !r.match).length;
  return (
    <section className="flex flex-col gap-4" data-testid="sap-readback" aria-label="SAP read-back">
      <div
        className={cn(
          "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border p-4",
          view.all_match
            ? "border-success/40 bg-success/8"
            : "border-destructive/40 bg-destructive/5",
        )}
        data-testid="readback-result"
        data-match={view.all_match ? "true" : "false"}
      >
        {view.all_match ? (
          <CircleCheck className="size-5 text-success" />
        ) : (
          <TriangleAlert className="size-5 text-destructive" />
        )}
        <p className="font-medium">
          {view.all_match
            ? `SAP saved exactly what we sent: all ${view.rows.length} fields match. No re-keying.`
            : `${mismatches} of ${view.rows.length} fields differ between what we sent and what SAP saved.`}
        </p>
        <div className="ml-auto flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">{RESOURCE_TEXT[view.resource]} code</span>
          <span className="font-semibold tabular-nums" data-testid="sap-code">
            {view.sap_code}
          </span>
          <Badge
            variant="secondary"
            className={view.active ? "bg-success/12 text-success-foreground" : undefined}
            data-testid="sap-active"
          >
            {view.active ? "Active in SAP" : "Inactive until checked"}
          </Badge>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Published by {view.published_by} on {formatSgt(view.published_at)} (demo clock). The record
        is created inactive, read back from SAP and compared, and only switched on when every field
        matches.
      </p>
      <div className="overflow-hidden rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">SAP field</th>
              <th className="px-4 py-2 font-medium">What we sent</th>
              <th className="px-4 py-2 font-medium">What SAP saved</th>
              <th className="w-24 px-4 py-2 font-medium">Match</th>
            </tr>
          </thead>
          <tbody>
            {view.rows.map((r) => (
              <tr
                key={r.field}
                className={cn("border-t", !r.match && "bg-destructive/5")}
                data-testid="readback-row"
                data-match={r.match ? "true" : "false"}
              >
                <td className="px-4 py-2 font-mono text-xs">{r.field}</td>
                <td className="px-4 py-2 break-all">{r.sent ?? <Empty />}</td>
                <td className="px-4 py-2 break-all">{r.read_back ?? <Empty />}</td>
                <td className="px-4 py-2">
                  {r.match ? (
                    <span className="inline-flex items-center gap-1 text-success-foreground">
                      <Check className="size-4" /> Same
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-destructive">
                      <X className="size-4" /> Differs
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Empty() {
  return <span className="text-muted-foreground">(empty)</span>;
}
