"use client";

import { Check, Equal, Loader2, Minus, UserRoundCog, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { SEGMENT_ON } from "@/components/analytics/segmented";
import { MIN_REASON_LENGTH } from "@/components/dedup/duplicate-panel";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useActingUserId } from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { DEMO_RESET_EVENT } from "@/lib/demo-events";
import { countryName, formatDay, formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";

type Queue = Schema<"CleanupQueue">;
type Cluster = Schema<"CleanupCluster">;
type CleanupRecord = Schema<"CleanupRecord">;
type Filter = "all" | "not_reviewed" | "reviewed";

const PAGE = 20;

const FIELDS: { label: string; value: (r: CleanupRecord) => string | null | undefined }[] = [
  { label: "Name", value: (r) => r.CardName },
  { label: "Other name", value: (r) => r.CardForeignName },
  { label: "Tax ID", value: (r) => r.FederalTaxID },
  { label: "City", value: (r) => r.City },
  { label: "Country", value: (r) => (r.Country ? countryName(r.Country) : null) },
  { label: "Company", value: (r) => r.U_Entity },
  { label: "Phone", value: (r) => r.Phone1 },
  { label: "Email", value: (r) => r.EmailAddress },
  { label: "Created", value: (r) => (r.CreateDate ? formatDay(r.CreateDate) : null) },
  { label: "Created by", value: (r) => r.CreatedBy },
  { label: "Hospital group", value: (r) => r.group_name },
];

function explain(e: unknown, what: string): string {
  return isApiError(e) ? e.message : `${what} did not work. Please try again.`;
}

function pct(score: number): string {
  return `${Math.round(score * 100)}%`;
}

function RecordsSideBySide({ records }: { records: CleanupRecord[] }) {
  const rows = FIELDS.map((f) => ({ label: f.label, values: records.map((r) => f.value(r)) })).filter(
    (row) => row.values.some(Boolean),
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-sm" data-testid="cleanup-records">
        <colgroup>
          <col className="w-28" />
          {records.map((r) => (
            <col key={r.CardCode} />
          ))}
        </colgroup>
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th scope="col" className="pb-2 font-normal">
              <span className="sr-only">Field</span>
            </th>
            {records.map((r) => (
              <th key={r.CardCode} scope="col" className="pb-2 font-medium">
                Record {r.CardCode}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const filled = row.values.filter(Boolean);
            const same =
              filled.length === row.values.length && new Set(filled.map(String)).size === 1;
            return (
              <tr
                key={row.label}
                data-match={same ? "true" : "false"}
                className={cn("border-t align-top", same && "bg-warning/10")}
              >
                <th
                  scope="row"
                  className="py-2 pr-3 pl-2 text-left text-xs font-normal text-muted-foreground"
                >
                  <span className="inline-flex items-center gap-1">
                    {row.label}
                    {same && <Equal className="size-3 text-foreground" aria-label="the same" />}
                  </span>
                </th>
                {row.values.map((v, i) => (
                  <td key={i} className="py-2 pr-3 break-words">
                    {v || <span className="text-muted-foreground/60">Not given</span>}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// The matcher names each country's tax ID (MST in Vietnam, UEN in Singapore...); say what it is.
const TAX_ID_NAMES = /\b(UEN|SSM no\.|NPWP|MST|TIN)(?= )/g;
function plainReason(text: string): string {
  return text.replace(TAX_ID_NAMES, "tax ID ($1)");
}

function Reasons({ cluster }: { cluster: Cluster }) {
  const several = cluster.links.length > 1;
  return (
    <div className="flex flex-col gap-3" data-testid="cleanup-reasons">
      {cluster.links.map((link) => (
        <div key={`${link.a}-${link.b}`} className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">
            Why the duplicate check links {several ? `${link.a} and ${link.b}` : "them"} (match
            score {pct(link.score)})
          </p>
          <ul className="flex flex-col gap-1 text-sm">
            {link.reasons.map((r, i) => (
              <li
                key={i}
                className={cn(
                  "flex items-start gap-2",
                  r.against ? "text-muted-foreground" : "text-foreground",
                )}
                data-against={r.against ? "true" : "false"}
              >
                {r.against ? (
                  <Minus className="mt-0.5 size-3.5 shrink-0" aria-label="counts against" />
                ) : (
                  <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-label="supports" />
                )}
                {plainReason(r.text)}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function NotSameDialog({
  disabled,
  onConfirm,
}: {
  disabled: boolean;
  onConfirm: (reason: string) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const tooShort = reason.trim().length < MIN_REASON_LENGTH;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setReason("");
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled} data-testid="cleanup-not-same">
          <X data-icon="inline-start" />
          Not the same
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Why are these different customers?</DialogTitle>
          <DialogDescription>
            Your reason is saved with your decision in the audit log, so others can check it.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="cleanup-reason">Reason</Label>
          <Textarea
            id="cleanup-reason"
            rows={3}
            value={reason}
            data-testid="cleanup-reason"
            placeholder="For example: two different hospitals that share a parent company."
            onChange={(e) => setReason(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">At least {MIN_REASON_LENGTH} characters.</p>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost">Cancel</Button>
          </DialogClose>
          <Button
            disabled={tooShort || saving}
            data-testid="cleanup-reason-save"
            onClick={async () => {
              setSaving(true);
              const ok = await onConfirm(reason.trim());
              setSaving(false);
              if (ok) setOpen(false);
            }}
          >
            {saving && <Loader2 className="animate-spin" data-icon="inline-start" />}
            Save: not the same
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Decision({ cluster }: { cluster: Cluster }) {
  const d = cluster.decision;
  if (!d) return null;
  const confirmed = d.decision === "confirm";
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-lg border px-4 py-3 text-sm",
        confirmed ? "border-success/40 bg-success/5" : "bg-muted/40",
      )}
      data-testid="cleanup-decision"
      data-decision={d.decision}
    >
      <p className="flex items-center gap-2 font-medium">
        {confirmed ? (
          <Check className="size-4 text-success" aria-hidden />
        ) : (
          <X className="size-4 text-muted-foreground" aria-hidden />
        )}
        {confirmed ? "Link confirmed: the same customer" : "Marked as not the same customer"}
      </p>
      <p className="text-muted-foreground">
        By {d.decided_by}, {formatSgt(d.decided_at)}
      </p>
      {d.reason && <p>Reason: {d.reason}</p>}
    </div>
  );
}

function GroupCard({
  cluster,
  canDecide,
  onDecided,
}: {
  cluster: Cluster;
  canDecide: boolean;
  onDecided: (result: Schema<"CleanupDecisionResult">) => void;
}) {
  const actingUser = useActingUserId();
  const [busy, setBusy] = useState(false);

  async function decide(body: Schema<"CleanupDecisionIn">): Promise<boolean> {
    setBusy(true);
    try {
      const result = await api.POST("/cleanup/clusters/{cluster_id}/decision", {
        path: { cluster_id: cluster.cluster_id },
        body,
        actingUser,
      });
      onDecided(result);
      return true;
    } catch (e) {
      toast.error(explain(e, "Saving your decision"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  const open = cluster.status === "not_reviewed";
  return (
    <article
      className="flex flex-col gap-4 rounded-xl border bg-card px-5 py-4"
      data-testid="cleanup-group"
      data-cluster={cluster.cluster_id}
      data-status={cluster.status}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">
          {cluster.records.length} records, likely one customer
        </h2>
        <p className="text-xs text-muted-foreground">{cluster.certainty}</p>
      </header>
      <RecordsSideBySide records={cluster.records} />
      <Reasons cluster={cluster} />
      {open ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={!canDecide || busy}
            data-testid="cleanup-confirm"
            onClick={() => decide({ decision: "confirm" })}
          >
            {busy ? <Loader2 className="animate-spin" data-icon="inline-start" /> : <Check data-icon="inline-start" />}
            Confirm link
          </Button>
          <NotSameDialog
            disabled={!canDecide || busy}
            onConfirm={(reason) => decide({ decision: "not_same", reason })}
          />
        </div>
      ) : (
        <Decision cluster={cluster} />
      )}
    </article>
  );
}

export function CleanupQueue() {
  const actingUser = useActingUserId();
  const [queue, setQueue] = useState<Queue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [shown, setShown] = useState(PAGE);

  useEffect(() => {
    if (!actingUser) return;
    let current = true;
    api.GET("/cleanup/clusters", { actingUser }).then(
      (next) => {
        if (!current) return;
        setQueue(next);
        setError(null);
      },
      (e: unknown) => current && setError(explain(e, "Loading the clean-up queue")),
    );
    return () => {
      current = false;
    };
  }, [actingUser, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  useEffect(() => {
    window.addEventListener(DEMO_RESET_EVENT, reload);
    return () => window.removeEventListener(DEMO_RESET_EVENT, reload);
  }, [reload]);

  const onDecided = useCallback((result: Schema<"CleanupDecisionResult">) => {
    setQueue((q) =>
      q
        ? {
            ...q,
            reviewed: result.reviewed,
            total: result.total,
            clusters: q.clusters.map((c) =>
              c.cluster_id === result.cluster.cluster_id ? result.cluster : c,
            ),
          }
        : q,
    );
    toast.success(
      result.cluster.status === "confirmed" ? "Link confirmed" : "Saved: not the same customer",
    );
  }, []);

  const visible = (queue?.clusters ?? []).filter((c) =>
    filter === "all" ? true : filter === "not_reviewed" ? c.status === "not_reviewed" : c.status !== "not_reviewed",
  );

  return (
    <div className="flex flex-col gap-8">
      <header className="flex max-w-3xl flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Clean-up queue</h1>
        <p className="text-base text-muted-foreground">
          Groups of customer records our duplicate check thinks are the same customer, most certain
          first. Confirm each link or mark it as not the same.
        </p>
        <p className="text-sm text-muted-foreground">
          Customer and vendor records for the same company are never grouped, and neither are
          records in different countries.
        </p>
      </header>

      {queue && !queue.can_decide && (
        <div
          className="flex items-center gap-3 rounded-xl border bg-muted/30 p-4 text-sm"
          data-testid="cleanup-readonly"
        >
          <UserRoundCog className="size-4 shrink-0 text-muted-foreground" />
          <p>{queue.note}</p>
        </div>
      )}

      {error && !queue ? (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed p-6 text-sm">
          <p>{error}</p>
          <Button variant="outline" size="sm" onClick={reload}>
            Try again
          </Button>
        </div>
      ) : !queue ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <p className="text-lg font-semibold tabular-nums" data-testid="cleanup-counter">
              {queue.reviewed} of {queue.total} reviewed
            </p>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              spacing={0}
              value={filter}
              onValueChange={(v) => {
                if (!v) return;
                setFilter(v as Filter);
                setShown(PAGE);
              }}
              aria-label="Which groups to show"
              data-testid="cleanup-filter"
            >
              <ToggleGroupItem value="all" className={SEGMENT_ON}>
                All
              </ToggleGroupItem>
              <ToggleGroupItem value="not_reviewed" className={SEGMENT_ON} data-testid="filter-open">
                Not reviewed
              </ToggleGroupItem>
              <ToggleGroupItem value="reviewed" className={SEGMENT_ON}>
                Reviewed
              </ToggleGroupItem>
            </ToggleGroup>
          </div>

          {visible.length === 0 ? (
            <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
              {filter === "reviewed" ? "Nothing reviewed yet." : "Every group has been reviewed."}
            </p>
          ) : (
            <div className="flex flex-col gap-5" data-testid="cleanup-list">
              {visible.slice(0, shown).map((c) => (
                <GroupCard
                  key={c.cluster_id}
                  cluster={c}
                  canDecide={queue.can_decide}
                  onDecided={onDecided}
                />
              ))}
            </div>
          )}
          {visible.length > shown && (
            <Button
              variant="outline"
              className="self-start"
              onClick={() => setShown((n) => n + PAGE)}
              data-testid="cleanup-more"
            >
              Show {Math.min(PAGE, visible.length - shown)} more (
              {visible.length - shown} not shown yet)
            </Button>
          )}
        </>
      )}
    </div>
  );
}
