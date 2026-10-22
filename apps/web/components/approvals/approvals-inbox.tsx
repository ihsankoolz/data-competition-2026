"use client";

import { ArrowUpRight, Inbox, Lock } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useClock } from "@/components/shell/clock-provider";
import { usePersona } from "@/components/shell/persona-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SlaBadge } from "@/components/workflow/badges";
import { DecisionActions } from "@/components/workflow/decision-actions";
import { RequestFields } from "@/components/workflow/request-fields";
import { useActingUserId } from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";
import { requestContext, roleLabel } from "@/lib/workflow";

type InboxItem = Schema<"ApprovalInboxItem">;
type RequestDetail = Schema<"RequestDetail">;

function explain(e: unknown): string {
  if (isApiError(e) && e.status === 501) return "Approvals aren't switched on in this build yet.";
  return isApiError(e) ? e.message : "Your approvals could not be loaded.";
}

export function ApprovalsInbox() {
  const actingUser = useActingUserId();
  const { persona } = usePersona();
  const { clock } = useClock();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The selection belongs to one persona; switching persona starts from the top of the new inbox.
  const [selection, setSelection] = useState<{ user: string | null; task: string } | null>(null);
  const selected = selection?.user === actingUser ? selection.task : null;
  const setSelected = (task: string | null) =>
    setSelection(task ? { user: actingUser, task } : null);
  const [attempt, setAttempt] = useState(0);
  const now = clock?.now;

  useEffect(() => {
    if (!actingUser) return;
    let current = true;
    api.GET("/approvals/inbox").then(
      (list) => {
        if (!current) return;
        setItems(list);
        setError(null);
      },
      (e: unknown) => current && setError(explain(e)),
    );
    return () => {
      current = false;
    };
  }, [actingUser, now, attempt]);

  const active =
    items?.find((i) => i.task.task_id === selected) ??
    (items && items.length > 0 ? items[0] : null);

  return (
    <div className="flex flex-col gap-8">
      <header className="flex max-w-3xl flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Approvals</h1>
        <p className="text-base text-muted-foreground">
          Requests waiting for {persona ? `${persona.name}'s` : "your"} decision, oldest due date
          first. Approve, reject, or ask the requestor for more information.
        </p>
      </header>

      {error ? (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed p-6 text-sm">
          <p>{error}</p>
          <Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
        </div>
      ) : items === null ? (
        <div className="grid grid-cols-[minmax(0,24rem)_minmax(0,1fr)] gap-8" aria-busy>
          <div className="flex flex-col gap-2">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
          <Skeleton className="h-80 w-full" />
        </div>
      ) : items.length === 0 ? (
        <div
          className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed text-center"
          data-testid="approvals-empty"
        >
          <Inbox className="size-6 text-muted-foreground" />
          <p className="max-w-sm text-sm text-muted-foreground">
            Nothing waits for {persona?.name ?? "you"} right now. When a request needs your decision
            it appears here, and the bell at the top lights up.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[minmax(0,24rem)_minmax(0,1fr)] items-start gap-8">
          <ul
            className="flex flex-col gap-2"
            aria-label="Waiting for you"
            data-testid="approvals-list"
          >
            {items.map((item) => {
              const isActive = active?.task.task_id === item.task.task_id;
              return (
                <li key={item.task.task_id}>
                  <button
                    type="button"
                    onClick={() => setSelected(item.task.task_id)}
                    aria-current={isActive ? "true" : undefined}
                    data-testid="approval-item"
                    data-req={item.request.req_id}
                    className={cn(
                      "flex w-full flex-col gap-1.5 rounded-xl border p-4 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      isActive ? "border-foreground/30 bg-muted/50" : "hover:bg-muted/40",
                    )}
                  >
                    <span className="flex items-start justify-between gap-3">
                      <span className="text-sm font-medium">{item.request.title}</span>
                      {item.task.sla_state && <SlaBadge state={item.task.sla_state} />}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {requestContext(item.request)}, from {item.request.requestor_name}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      You decide as {roleLabel(item.task)}
                      {item.task.due_at ? `, due ${formatSgt(item.task.due_at)}` : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {active && (
            <TaskPane
              key={active.task.task_id}
              item={active}
              isFinance={!!persona?.roles.includes("finance")}
              onDecided={() => {
                setSelected(null);
                setAttempt((n) => n + 1);
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}

function TaskPane({
  item,
  isFinance,
  onDecided,
}: {
  item: InboxItem;
  isFinance: boolean;
  onDecided: (d: RequestDetail) => void;
}) {
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reqId = item.request.req_id;

  useEffect(() => {
    let current = true;
    api.GET("/requests/{req_id}", { path: { req_id: reqId } }).then(
      (d) => current && setDetail(d),
      (e: unknown) =>
        current && setError(isApiError(e) ? e.message : "The request could not be loaded."),
    );
    return () => {
      current = false;
    };
  }, [reqId]);

  const others = (item.request.pending_with ?? []).length;

  return (
    <section
      className="flex flex-col gap-6 rounded-xl border p-6"
      aria-label={`Decide on ${item.request.title}`}
      data-testid="approval-pane"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <p className="text-sm text-muted-foreground">
            {reqId}, {requestContext(item.request)}
          </p>
          <h2 className="text-xl font-semibold tracking-tight">{item.request.title}</h2>
          <p className="text-sm text-muted-foreground">
            Asked by {item.request.requestor_name} on {formatSgt(item.request.created_at)}.{" "}
            {others > 1
              ? `${others} people are deciding at the same time, including you.`
              : "You are the last decision in this stage."}
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href={`/requests/${reqId}`} data-testid="open-request">
            Full status
            <ArrowUpRight data-icon="inline-end" />
          </Link>
        </Button>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold">Details to check</h3>
        {error ? (
          <p className="text-sm text-muted-foreground">{error}</p>
        ) : detail ? (
          <RequestFields detail={detail} />
        ) : (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-5 w-full max-w-lg" />
            ))}
          </div>
        )}
        {!isFinance && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Lock className="size-3" />
            Bank details are hidden unless you are in Finance.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2 border-t pt-5">
        <p className="text-sm">
          <span className="font-medium">Your decision</span>
          <span className="text-muted-foreground"> as {roleLabel(item.task)}</span>
        </p>
        <DecisionActions
          taskId={item.task.task_id}
          title={item.request.title}
          onDecided={onDecided}
        />
      </div>
    </section>
  );
}
