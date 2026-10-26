"use client";

import { Check, CircleAlert, Link2, Loader2, ShieldCheck, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schema } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import { type DedupDecision, NotDuplicateDialog } from "./duplicate-panel";
import type { ItemDedupResult, ItemDedupState } from "./use-item-dedup-check";

type ItemCandidate = Schema<"ItemCandidate">;

const GROUP_NAME: Record<number, string> = {
  101: "Reagents and test kits",
  102: "Analysers and equipment",
  103: "Service contracts",
};

function VerdictBanner({ result }: { result: ItemDedupResult }) {
  if (result.verdict === "none") {
    return (
      <div className="flex items-start gap-3 text-sm" data-testid="verdict" data-verdict="none">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" />
        <p>{result.message || "No existing item matched. You can submit."}</p>
      </div>
    );
  }
  const likely = result.verdict === "likely";
  return (
    <div
      role="alert"
      data-testid="verdict"
      data-verdict={result.verdict}
      className={cn(
        "flex items-start gap-3 rounded-lg border p-3 text-sm",
        likely ? "border-destructive/40 bg-destructive/5" : "border-warning/50 bg-warning/10",
      )}
    >
      {likely ? (
        <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
      ) : (
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning-foreground" />
      )}
      <div className="flex flex-col gap-1">
        <p className="font-medium">
          {likely ? "Likely the same item: submit is paused" : "Possibly the same item: please check"}
        </p>
        <p className="text-muted-foreground">{result.message}</p>
        <p className="text-muted-foreground">
          {likely
            ? "You decide; the system never links items on its own."
            : "You can still submit. Compare the items below and decide."}
        </p>
      </div>
    </div>
  );
}

function CandidateCard({
  c,
  typedName,
  busy,
  onLink,
}: {
  c: ItemCandidate;
  typedName: string;
  busy: boolean;
  onLink: (itemCode: string) => void;
}) {
  return (
    <article
      className="flex flex-col gap-3"
      data-testid="candidate"
      aria-label={`Existing item ${c.ItemCode}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">
          {c.ItemName} <span className="font-normal text-muted-foreground">{c.ItemCode}</span>
        </h3>
        <Badge variant={c.verdict === "likely" ? "destructive" : "secondary"}>
          {c.verdict === "likely" ? "Likely the same" : "Possibly the same"}
        </Badge>
      </div>
      <div>
        <Button onClick={() => onLink(c.ItemCode)} disabled={busy} data-testid={`link-${c.ItemCode}`}>
          {busy ? (
            <Loader2 className="animate-spin" data-icon="inline-start" />
          ) : (
            <Link2 data-icon="inline-start" />
          )}
          Use existing item {c.ItemCode}
        </Button>
      </div>
      <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1 text-sm" data-testid="comparison">
        <dt className="text-xs text-muted-foreground">Your item</dt>
        <dd className="break-words">{typedName || "Not given"}</dd>
        <dt className="text-xs text-muted-foreground">Existing item</dt>
        <dd className="break-words">{c.ItemName}</dd>
        {c.sales_unit && (
          <>
            <dt className="text-xs text-muted-foreground">Sold as</dt>
            <dd>{c.sales_unit}</dd>
          </>
        )}
        {c.ItemsGroupCode != null && (
          <>
            <dt className="text-xs text-muted-foreground">Item group</dt>
            <dd>{GROUP_NAME[c.ItemsGroupCode] ?? c.ItemsGroupCode}</dd>
          </>
        )}
      </dl>
      {c.reasons && c.reasons.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">Why we think so</p>
          <ul className="flex flex-col gap-1 text-sm" data-testid="reasons">
            {c.reasons.map((r) => (
              <li
                key={`${r.layer}-${r.text}`}
                className={cn(
                  "flex items-start gap-2",
                  (r.weight ?? 0) < 0 && "text-muted-foreground",
                )}
              >
                <Check className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                {r.text}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

export type ItemDuplicatePanelProps = {
  state: ItemDedupState;
  typedName: string;
  decision: DedupDecision | null;
  busy: boolean;
  error: string | null;
  onLink: (itemCode: string) => void;
  onNotDuplicate: (reason: string) => Promise<boolean>;
};

/** Session 13: the item form's duplicate panel. Rules only; a person makes every choice. */
export function ItemDuplicatePanel(props: ItemDuplicatePanelProps) {
  const { state, decision } = props;
  return (
    <section
      aria-label="Duplicate check"
      data-testid="item-dup-panel"
      className="flex flex-col gap-4 rounded-xl border bg-card p-5"
    >
      <header className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold">Duplicate check</h2>
        {state.status === "checking" && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Checking
          </span>
        )}
      </header>
      {decision?.action === "link_to_existing" ? (
        <div
          className="flex items-start gap-3 rounded-lg border border-success/40 bg-success/10 p-4"
          data-testid="linked"
          role="status"
        >
          <Link2 className="mt-0.5 size-5 shrink-0 text-success-foreground" />
          <div className="flex flex-col gap-1">
            <p className="font-medium">
              Using existing item{" "}
              {decision.card_name ? `${decision.card_name} (${decision.card_code})` : decision.card_code}
              .
            </p>
            <p className="text-sm text-muted-foreground">
              No new item and no approval needed; nothing was sent to an approver.
            </p>
          </div>
        </div>
      ) : (
        <PanelBody {...props} />
      )}
    </section>
  );
}

function PanelBody({
  state,
  typedName,
  decision,
  busy,
  error,
  onLink,
  onNotDuplicate,
}: ItemDuplicatePanelProps) {
  if (state.status === "idle") {
    return (
      <p className="text-sm text-muted-foreground">
        Type the item name. We check the catalogue as you type, so the same product is not created
        twice. A catalogue number or registration number makes the check sharper.
      </p>
    );
  }
  if (state.status === "unavailable") {
    return (
      <p
        className="flex items-start gap-2 text-sm text-muted-foreground"
        data-testid="dup-unavailable"
      >
        <CircleAlert className="mt-0.5 size-4 shrink-0" />
        {state.message}
      </p>
    );
  }
  const result = state.status === "done" ? state.result : state.previous;
  if (!result) {
    return (
      <div className="flex flex-col gap-2" aria-busy>
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  const candidates = result.candidates ?? [];
  return (
    <div className={cn("flex flex-col gap-5", state.status === "checking" && "opacity-60")}>
      <VerdictBanner result={result} />
      {candidates.map((c) => (
        <CandidateCard key={c.ItemCode} c={c} typedName={typedName} busy={busy} onLink={onLink} />
      ))}
      {candidates.length > 0 && (
        <div className="flex flex-col gap-2 border-t pt-4">
          {decision?.action === "not_duplicate" ? (
            <div
              className="flex items-start gap-2 text-sm"
              data-testid="override-saved"
              role="status"
            >
              <Check className="mt-0.5 size-4 shrink-0 text-success" />
              <p>
                You marked this as a new item: <q>{decision.reason}</q>. You can submit now.
              </p>
            </div>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">Sure it is a different product?</p>
              <div>
                <NotDuplicateDialog domain="item" disabled={busy} onConfirm={onNotDuplicate} />
              </div>
            </>
          )}
        </div>
      )}
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Rules only, no AI: name without pack size, catalogue number and registration number.
        Demo catalogue numbers are synthetic.
      </p>
    </div>
  );
}
