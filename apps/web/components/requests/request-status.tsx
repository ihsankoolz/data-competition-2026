"use client";

import { Check, CircleDashed, Clock, Link2, X } from "lucide-react";
import Link from "next/link";
import { use, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { countryName, formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";

type RequestDetail = Schema<"RequestDetail">;

const STATE_TEXT: Record<RequestDetail["state"], string> = {
  DRAFT: "Draft, not submitted yet",
  SUBMITTED: "Submitted",
  IN_APPROVAL: "Waiting for approvals",
  INFO_REQUESTED: "An approver asked for more information",
  REJECTED: "Rejected",
  APPROVED: "Approved, ready to publish to SAP",
  PUBLISHED_INACTIVE: "Sent to SAP, being checked",
  ACTIVE: "Live in SAP",
  LINKED_TO_EXISTING: "Linked to an existing record",
};

const TASK_TEXT: Record<Schema<"ApprovalTask">["status"], string> = {
  waiting: "Not started yet",
  pending: "Deciding",
  approved: "Approved",
  rejected: "Rejected",
  info_requested: "Asked for more information",
  cancelled: "Not needed",
};

function TaskIcon({ status }: { status: Schema<"ApprovalTask">["status"] }) {
  if (status === "approved") return <Check className="size-4 text-success" />;
  if (status === "rejected") return <X className="size-4 text-destructive" />;
  if (status === "pending" || status === "info_requested")
    return <Clock className="size-4 text-warning-foreground" />;
  return <CircleDashed className="size-4 text-muted-foreground" />;
}

/** Minimal status view: state, link, and each stage's approvers. The full timeline comes later. */
export function RequestStatus({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    api.GET("/requests/{req_id}", { path: { req_id: id } }).then(
      (d) => current && setDetail(d),
      (e: unknown) => {
        if (!current) return;
        if (isApiError(e) && e.status === 501) {
          setError("Request details aren't switched on in this build yet.");
        } else if (isApiError(e) && e.status === 404) {
          setError(`There is no request ${id}. It may have been cleared by "Reset demo".`);
        } else {
          setError(isApiError(e) ? e.message : "The request could not be loaded.");
        }
      },
    );
    return () => {
      current = false;
    };
  }, [id, attempt]);

  if (error) {
    return (
      <div className="flex max-w-xl flex-col items-start gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Request {id}</h1>
        <p className="text-muted-foreground">{error}</p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <Link href="/requests/new">New request</Link>
          </Button>
        </div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex flex-col gap-4" aria-busy aria-label="Loading the request">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-5 w-96" />
        <Skeleton className="h-40 w-full max-w-3xl" />
      </div>
    );
  }

  const stages = detail.stages ?? [];
  return (
    <div className="flex max-w-3xl flex-col gap-8" data-testid="request-status">
      <header className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          Request {detail.req_id}, {detail.domain}, {detail.entity}, {countryName(detail.country)}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{detail.title}</h1>
        <div className="flex items-center gap-3">
          <Badge variant="secondary" data-testid="request-state" data-state={detail.state}>
            {STATE_TEXT[detail.state]}
          </Badge>
          <span className="text-sm text-muted-foreground">
            Requested by {detail.requestor_name} on {formatSgt(detail.created_at)}
          </span>
        </div>
      </header>

      {detail.state === "LINKED_TO_EXISTING" && (
        <div className="flex items-start gap-3 rounded-lg border border-success/40 bg-success/10 p-4">
          <Link2 className="mt-0.5 size-5 shrink-0 text-success-foreground" />
          <p>
            Linked to {detail.linked_card_code}. No approval needed; the duplicate never reached an
            approver.
          </p>
        </div>
      )}

      {(detail.pending_with ?? []).length > 0 && (
        <p className="text-sm">
          <span className="font-medium">Waiting on:</span> {detail.pending_with!.join(", ")}
        </p>
      )}

      {stages.length > 0 && (
        <ol className="flex flex-col gap-4" aria-label="Approval stages">
          {stages.map((s) => (
            <li key={s.number} className="flex flex-col gap-2 rounded-xl border p-4">
              <p className="text-sm font-medium">
                Stage {s.number}: {s.name}
                <span className="ml-2 font-normal text-muted-foreground">
                  {s.status === "open"
                    ? "in progress, approvers decide in parallel"
                    : s.status === "done"
                      ? "done"
                      : s.status === "rejected"
                        ? "rejected"
                        : "starts when the stage before it is done"}
                </span>
              </p>
              <ul className="flex flex-col gap-1.5">
                {s.tasks.map((t) => (
                  <li
                    key={t.task_id}
                    className={cn("flex items-center gap-2 text-sm", t.status === "waiting" && "text-muted-foreground")}
                  >
                    <TaskIcon status={t.status} />
                    <span className="font-medium">{t.assignee_name}</span>
                    <span className="text-muted-foreground">{TASK_TEXT[t.status]}</span>
                    {t.due_at && t.status === "pending" && (
                      <span className="text-muted-foreground">, due {formatSgt(t.due_at)}</span>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
