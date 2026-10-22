import { usdShort } from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";
import { cn } from "@/lib/utils";

type Panel = Schema<"PanelCount">;

const ORDER: Panel["kind"][] = ["confirmed_po", "enquiry", "purchase_request", "mdm_request"];

const ROLE: Record<Panel["kind"], string> = {
  confirmed_po: "Demand",
  enquiry: "Early signal",
  purchase_request: "Early signal",
  mdm_request: "Never demand",
};

/** POs, enquiries, purchase requests and MDM requests, deliberately in separate boxes (rule 9). */
export function SignalPanels({ panels }: { panels: Panel[] }) {
  const sorted = ORDER.map((k) => panels.find((p) => p.kind === k)).filter((p): p is Panel => !!p);
  return (
    <ul className="grid grid-cols-4 gap-4" data-testid="signal-panels">
      {sorted.map((p) => {
        const demand = p.kind === "confirmed_po";
        return (
          <li
            key={p.kind}
            data-testid={`panel-${p.kind}`}
            className={cn(
              "flex flex-col gap-2 rounded-xl border p-4",
              demand ? "border-foreground/25 bg-background" : "border-dashed bg-muted/20",
            )}
          >
            <span className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{p.label}</span>
              <span
                className={cn(
                  "shrink-0 rounded-full px-2 py-0.5 text-[11px] whitespace-nowrap",
                  demand ? "bg-foreground text-background" : "bg-muted text-muted-foreground",
                )}
              >
                {ROLE[p.kind]}
              </span>
            </span>
            <span className="text-2xl font-semibold tabular-nums">
              {p.count.toLocaleString("en-US")}
            </span>
            <span className="text-sm text-muted-foreground tabular-nums">
              {p.value_usd === null || p.value_usd === undefined
                ? "No value: never counted as demand"
                : demand
                  ? `${usdShort(p.value_usd)} of orders`
                  : `${usdShort(p.value_usd)} mentioned, not counted`}
            </span>
            <span className="text-xs text-muted-foreground">{p.caption}</span>
          </li>
        );
      })}
    </ul>
  );
}
