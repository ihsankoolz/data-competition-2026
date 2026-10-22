"use client";

import {
  ArrowRight,
  BellRing,
  Check,
  CircleDashed,
  Clock,
  Forward,
  Link2,
  Loader2,
  MessageCircleQuestion,
  SendHorizontal,
  X,
} from "lucide-react";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useClock } from "@/components/shell/clock-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SlaBadge, StateBadge } from "@/components/workflow/badges";
import { DecisionActions } from "@/components/workflow/decision-actions";
import { RequestFields } from "@/components/workflow/request-fields";
import { ReadbackUnavailable, SapReadback } from "@/components/workflow/sap-readback";
import { useActingUserId } from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";
import { type ApprovalTask, requestContext, roleLabel, TASK_TEXT } from "@/lib/workflow";

type RequestDetail = Schema<"RequestDetail">;
type AuditEntry = Schema<"AuditEntry">;
type Stage = Schema<"Stage">;

function TaskIcon({ status }: { status: ApprovalTask["status"] }) {
  if (status === "approved") return <Check className="size-4 text-success" />;
  if (status === "rejected") return <X className="size-4 text-destructive" />;
  if (status === "info_requested")
    return <MessageCircleQuestion className="size-4 text-warning-foreground" />;
  if (status === "pending") return <Clock className="size-4 text-warning-foreground" />;
  return <CircleDashed className="size-4 text-muted-foreground" />;
}

const STAGE_TEXT: Record<Stage["status"], string> = {
  open: "In progress: everyone below decides at the same time",
  done: "Done",
  rejected: "Stopped: rejected",
  waiting: "Starts when the stage before it is done",
};

function explainLoad(e: unknown, id: string): string {
  if (isApiError(e) && e.status === 501)
    return "Request details aren't available right now. Try again in a moment.";
  if (isApiError(e) && e.status === 404) {
    return `There is no request ${id}. It may have been cleared by "Reset demo".`;
  }
  return isApiError(e) ? e.message : "The request could not be loaded.";
}

const REFRESH_MS = 8_000;
const LIVE_STATES = new Set<RequestDetail["state"]>([
  "SUBMITTED",
  "IN_APPROVAL",
  "INFO_REQUESTED",
  "APPROVED",
]);

/** Loads one request and its audit trail; reloads when the demo clock or the persona changes. */
function useRequest(id: string) {
  const { clock } = useClock();
  const actingUser = useActingUserId();
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const now = clock?.now;

  useEffect(() => {
    if (!actingUser) return;
    let current = true;
    api.GET("/requests/{req_id}", { path: { req_id: id } }).then(
      (d) => {
        if (!current) return;
        setDetail(d);
        setError(null);
      },
      (e: unknown) => current && setError(explainLoad(e, id)),
    );
    api.GET("/requests/{req_id}/audit", { path: { req_id: id } }).then(
      (a) => {
        if (!current) return;
        setAudit(a);
        setAuditError(null);
      },
      (e: unknown) =>
        current && setAuditError(isApiError(e) ? e.message : "The history could not be loaded."),
    );
    return () => {
      current = false;
    };
  }, [id, attempt, now, actingUser]);

  // While other people can still act on it, check again every few seconds.
  const live = !!detail && LIVE_STATES.has(detail.state);
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setAttempt((n) => n + 1), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [live]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { detail, setDetail, audit, auditError, error, reload };
}

export function RequestStatus({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const actingUser = useActingUserId();
  const { detail, setDetail, audit, auditError, error, reload } = useRequest(id);

  if (error) {
    return (
      <div className="flex max-w-xl flex-col items-start gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Request {id}</h1>
        <p className="text-muted-foreground">{error}</p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={reload}>
            Try again
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <Link href="/requests">My requests</Link>
          </Button>
        </div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex flex-col gap-4" aria-busy aria-label="Loading the request">
        <Skeleton className="h-5 w-72" />
        <Skeleton className="h-8 w-96" />
        <Skeleton className="h-12 w-full max-w-4xl" />
        <Skeleton className="h-56 w-full" />
      </div>
    );
  }

  const stages = detail.stages ?? [];
  const actions = detail.allowed_actions ?? [];
  const myTask = stages
    .flatMap((s) => s.tasks)
    .find(
      (t) =>
        t.status === "pending" &&
        (t.assignee_user_id === actingUser || t.escalated_to_user_id === actingUser),
    );
  const pendingWith = detail.pending_with ?? [];

  const onDecided = (next: RequestDetail) => {
    setDetail(next);
    reload();
  };

  return (
    <div className="flex flex-col gap-8" data-testid="request-status">
      <header className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          {detail.req_id}, {requestContext(detail)}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{detail.title}</h1>
        <div className="flex flex-wrap items-center gap-3">
          <StateBadge state={detail.state} />
          <span className="text-sm text-muted-foreground">
            Requested by {detail.requestor_name} on {formatSgt(detail.created_at)}
          </span>
        </div>
      </header>

      {detail.state === "LINKED_TO_EXISTING" && (
        <div className="flex items-start gap-3 rounded-xl border border-success/40 bg-success/8 p-4">
          <Link2 className="mt-0.5 size-5 shrink-0 text-success-foreground" />
          <p>
            Linked to {detail.linked_card_code}. No approval needed; the duplicate never reached an
            approver.
          </p>
        </div>
      )}

      {pendingWith.length > 0 && (
        <p className="text-lg" data-testid="pending-with">
          <span className="text-muted-foreground">Waiting on </span>
          <span className="font-medium">{listNames(pendingWith)}</span>
        </p>
      )}

      <YourTurn
        detail={detail}
        actions={actions}
        myTask={myTask}
        onDecided={onDecided}
        onChanged={reload}
      />

      {stages.length > 0 && <StageFlow stages={stages} />}

      {detail.sap_publish ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-base font-semibold">In SAP Business One</h2>
          <SapReadback view={detail.sap_publish} />
        </section>
      ) : (
        (detail.state === "ACTIVE" || detail.state === "PUBLISHED_INACTIVE") && (
          <section className="flex flex-col gap-3">
            <h2 className="text-base font-semibold">In SAP Business One</h2>
            <ReadbackUnavailable />
          </section>
        )
      )}

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,26rem)] items-start gap-10">
        <section className="flex flex-col gap-3" aria-label="Request details">
          <h2 className="text-base font-semibold">What was asked for</h2>
          <RequestFields detail={detail} />
        </section>
        <section className="flex flex-col gap-3" aria-label="History">
          <h2 className="text-base font-semibold">History</h2>
          <p className="-mt-2 text-xs text-muted-foreground">
            Every change, who made it and when (demo clock). Bank details are never written here.
          </p>
          <AuditTimeline entries={audit} error={auditError} />
        </section>
      </div>
    </div>
  );
}

function listNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}

function YourTurn({
  detail,
  actions,
  myTask,
  onDecided,
  onChanged,
}: {
  detail: RequestDetail;
  actions: NonNullable<RequestDetail["allowed_actions"]>;
  myTask: ApprovalTask | undefined;
  onDecided: (d: RequestDetail) => void;
  onChanged: () => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const canDecide = actions.includes("approve") && myTask;
  const canPublish = actions.includes("publish");
  const canResubmit = actions.includes("submit") && detail.state === "INFO_REQUESTED";
  if (!canDecide && !canPublish && !canResubmit) return null;

  async function resubmit() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await api.POST("/requests/{req_id}/submit", { path: { req_id: detail.req_id } });
      toast.success("Sent back to the approvers");
      onChanged();
    } catch (e) {
      setSubmitError(isApiError(e) ? e.message : "The request was not sent. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section
      className="flex flex-col gap-3 rounded-xl border bg-muted/30 p-5"
      aria-label="Your decision"
      data-testid="your-turn"
    >
      {canDecide && myTask && (
        <>
          <p className="text-sm">
            <span className="font-medium">Your decision</span>
            <span className="text-muted-foreground">
              {" "}
              as {roleLabel(myTask)}
              {myTask.due_at ? `, due ${formatSgt(myTask.due_at)}` : ""}
            </span>
          </p>
          <DecisionActions taskId={myTask.task_id} title={detail.title} onDecided={onDecided} />
        </>
      )}
      {canPublish && (
        <div className="flex items-center gap-4">
          <p className="text-sm">Every approval is in. This record is ready to go to SAP.</p>
          <Button asChild>
            <Link href="/publish">
              <SendHorizontal data-icon="inline-start" />
              Go to Publish to SAP
            </Link>
          </Button>
        </div>
      )}
      {canResubmit && (
        <div className="flex flex-col gap-2">
          <p className="text-sm">
            An approver asked you a question (their comment is in the stage below). Answer it, then
            send the request back to the approvers.
          </p>
          <div>
            <Button onClick={() => void resubmit()} disabled={submitting} data-testid="resubmit">
              {submitting && <Loader2 className="animate-spin" data-icon="inline-start" />}
              Send back to approvers
            </Button>
          </div>
          {submitError && (
            <p className="text-sm text-destructive" role="alert">
              {submitError}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function StageFlow({ stages }: { stages: Stage[] }) {
  return (
    <ol className="flex items-stretch gap-3" aria-label="Approval stages">
      {stages.map((s, i) => (
        <li key={s.number} className="contents">
          {i > 0 && (
            <ArrowRight
              className="mt-6 size-4 shrink-0 self-start text-muted-foreground"
              aria-hidden
            />
          )}
          <div
            className={cn(
              "flex min-w-0 flex-col gap-3 rounded-xl border p-4",
              s.tasks.length > 1 ? "flex-[3]" : "flex-1",
              s.status === "waiting" && "border-dashed bg-muted/20",
              s.status === "done" && "border-success/30",
            )}
            data-testid={`stage-${s.number}`}
            data-status={s.status}
          >
            <div className="flex flex-col gap-0.5">
              <p className="text-sm font-medium">
                Stage {s.number}: {s.name}
              </p>
              <p className="text-xs text-muted-foreground">{STAGE_TEXT[s.status]}</p>
            </div>
            <ul
              className={cn(
                "grid gap-2",
                s.tasks.length > 1 && "grid-cols-[repeat(auto-fill,minmax(13rem,1fr))]",
              )}
            >
              {s.tasks.map((t) => (
                <TaskCard key={t.task_id} task={t} />
              ))}
            </ul>
          </div>
        </li>
      ))}
    </ol>
  );
}

function TaskCard({ task: t }: { task: ApprovalTask }) {
  const open = t.status === "pending" || t.status === "info_requested";
  return (
    <li
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border bg-background p-3 text-sm",
        t.status === "waiting" && "text-muted-foreground",
        t.status === "cancelled" && "opacity-60",
      )}
      data-testid="task"
      data-assignee={t.assignee_user_id}
      data-status={t.status}
    >
      <div className="flex items-center gap-2">
        <TaskIcon status={t.status} />
        <span className="font-medium">{t.assignee_name}</span>
      </div>
      <span className="text-xs text-muted-foreground">{roleLabel(t)}</span>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs">{TASK_TEXT[t.status]}</span>
        {open && t.sla_state && t.sla_state !== "done" && <SlaBadge state={t.sla_state} />}
      </div>
      {open && t.due_at && (
        <span className="text-xs text-muted-foreground">Due {formatSgt(t.due_at)}</span>
      )}
      {t.decided_at && !open && (
        <span className="text-xs text-muted-foreground">{formatSgt(t.decided_at)}</span>
      )}
      {t.reminded_at && (
        <span className="flex items-center gap-1 text-xs text-warning-foreground">
          <BellRing className="size-3" /> Reminder sent {formatSgt(t.reminded_at)}
        </span>
      )}
      {t.escalated_at && (
        <span className="flex items-center gap-1 text-xs text-destructive">
          <Forward className="size-3" /> Passed to a backup approver {formatSgt(t.escalated_at)}
        </span>
      )}
      {t.comment && <q className="mt-1 border-l-2 pl-2 text-xs text-foreground">{t.comment}</q>}
    </li>
  );
}

function AuditTimeline({ entries, error }: { entries: AuditEntry[] | null; error: string | null }) {
  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!entries) {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">Nothing yet.</p>;
  return (
    <ol className="flex flex-col" data-testid="audit-timeline">
      {entries.map((e) => (
        <li
          key={e.id}
          className="relative flex flex-col gap-0.5 border-l py-2 pl-4 before:absolute before:top-3.5 before:-left-[4.5px] before:size-2 before:rounded-full before:bg-border"
          data-testid="audit-entry"
        >
          <span className="text-sm">{e.summary}</span>
          <span className="text-xs text-muted-foreground">
            {e.actor} on {formatSgt(e.ts)}
          </span>
        </li>
      ))}
    </ol>
  );
}
