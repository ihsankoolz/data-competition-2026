"use client";

import { CircleCheck, Loader2, SendHorizontal, UserRoundCog } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { usePersona } from "@/components/shell/persona-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StateBadge } from "@/components/workflow/badges";
import { RequestFields } from "@/components/workflow/request-fields";
import { ReadbackUnavailable, SapReadback } from "@/components/workflow/sap-readback";
import { useActingUserId } from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { announceWorkflowChange } from "@/lib/demo-events";
import { formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";
import { requestContext } from "@/lib/workflow";

type RequestSummary = Schema<"RequestSummary">;
type RequestDetail = Schema<"RequestDetail">;
type SapPublishView = Schema<"SapPublishView">;

const RESOURCE: Record<RequestDetail["domain"], string> = {
  customer: "BusinessPartners",
  vendor: "BusinessPartners",
  item: "Items",
  cost_center: "ProfitCenters",
};

type Lists = { waiting: RequestSummary[]; published: RequestSummary[] };

function explain(e: unknown, what: string): string {
  if (isApiError(e) && e.status === 501)
    return `${what} isn't available right now. Try again in a moment.`;
  return isApiError(e) ? e.message : `${what} did not work. Please try again.`;
}

async function loadLists(): Promise<Lists> {
  const [waiting, active, inactive] = await Promise.all([
    api.GET("/requests", { query: { scope: "all", state: "APPROVED" } }),
    api.GET("/requests", { query: { scope: "all", state: "ACTIVE" } }),
    api.GET("/requests", { query: { scope: "all", state: "PUBLISHED_INACTIVE" } }),
  ]);
  const byUpdated = (a: RequestSummary, b: RequestSummary) =>
    b.updated_at.localeCompare(a.updated_at);
  return { waiting, published: [...inactive, ...active].sort(byUpdated) };
}

/** The read-back for a published request: from the detail, else the read-back endpoint. */
async function readbackFor(detail: RequestDetail): Promise<SapPublishView | null> {
  if (detail.sap_publish) return detail.sap_publish;
  try {
    return await api.GET("/requests/{req_id}/sap-readback", { path: { req_id: detail.req_id } });
  } catch {
    return null; // Not built yet (501) or not found: show the "not available yet" state.
  }
}

export function PublishScreen() {
  const actingUser = useActingUserId();
  const { persona } = usePersona();
  const [lists, setLists] = useState<Lists | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!actingUser) return;
    let current = true;
    loadLists().then(
      (next) => {
        if (!current) return;
        setLists(next);
        setError(null);
      },
      (e: unknown) => current && setError(explain(e, "Loading the publish list")),
    );
    return () => {
      current = false;
    };
  }, [actingUser, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const isAnalyst = !!persona?.roles.includes("mdm_analyst");
  const all = lists ? [...lists.waiting, ...lists.published] : [];
  const activeId =
    selected && all.some((r) => r.req_id === selected) ? selected : (all[0]?.req_id ?? null);

  return (
    <div className="flex flex-col gap-8">
      <header className="flex max-w-3xl flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Publish to SAP</h1>
        <p className="text-base text-muted-foreground">
          Fully approved records, sent to SAP Business One in one click. We read each record back
          from SAP and show what we sent next to what SAP saved, so nobody re-keys anything.
        </p>
      </header>

      {persona && !isAnalyst && (
        <div
          className="flex items-center gap-3 rounded-xl border bg-muted/30 p-4 text-sm"
          data-testid="not-analyst"
        >
          <UserRoundCog className="size-4 shrink-0 text-muted-foreground" />
          <p>
            Only a master-data analyst can publish. You are acting as {persona.name} (
            {persona.title}); switch to Priya in the top right to publish.
          </p>
        </div>
      )}

      {error ? (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed p-6 text-sm">
          <p>{error}</p>
          <Button variant="outline" size="sm" onClick={reload}>
            Try again
          </Button>
        </div>
      ) : !lists ? (
        <div className="grid grid-cols-[minmax(0,22rem)_minmax(0,1fr)] gap-8" aria-busy>
          <div className="flex flex-col gap-2">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-96 w-full" />
        </div>
      ) : all.length === 0 ? (
        <div
          className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed text-center"
          data-testid="publish-empty"
        >
          <SendHorizontal className="size-6 text-muted-foreground" />
          <p className="max-w-md text-sm text-muted-foreground">
            Nothing to publish yet. A request shows up here once every approver has said yes. See
            what is still waiting in{" "}
            <Link href="/requests" className="underline underline-offset-4">
              My requests
            </Link>
            .
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[minmax(0,22rem)_minmax(0,1fr)] items-start gap-8">
          <div className="flex flex-col gap-6">
            <RequestList
              title="Ready to publish"
              empty="Nothing is waiting. Every approved record is in SAP."
              items={lists.waiting}
              activeId={activeId}
              onSelect={setSelected}
              testId="publish-waiting"
            />
            {lists.published.length > 0 && (
              <RequestList
                title="Published"
                items={lists.published}
                activeId={activeId}
                onSelect={setSelected}
                testId="publish-done"
              />
            )}
          </div>
          {activeId && (
            <PublishPane
              key={activeId}
              reqId={activeId}
              canPublish={isAnalyst}
              onPublished={reload}
            />
          )}
        </div>
      )}
    </div>
  );
}

function RequestList({
  title,
  empty,
  items,
  activeId,
  onSelect,
  testId,
}: {
  title: string;
  empty?: string;
  items: RequestSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  testId: string;
}) {
  return (
    <section className="flex flex-col gap-2" aria-label={title}>
      <h2 className="text-sm font-semibold">
        {title} <span className="font-normal text-muted-foreground">({items.length})</span>
      </h2>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid={testId}>
          {items.map((r) => (
            <li key={r.req_id}>
              <button
                type="button"
                onClick={() => onSelect(r.req_id)}
                aria-current={r.req_id === activeId ? "true" : undefined}
                data-testid="publish-item"
                data-req={r.req_id}
                className={cn(
                  "flex w-full flex-col gap-1 rounded-xl border p-3.5 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  r.req_id === activeId ? "border-foreground/30 bg-muted/50" : "hover:bg-muted/40",
                )}
              >
                <span className="text-sm font-medium">{r.title}</span>
                <span className="text-xs text-muted-foreground">
                  {r.req_id}, {requestContext(r)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PublishPane({
  reqId,
  canPublish,
  onPublished,
}: {
  reqId: string;
  canPublish: boolean;
  onPublished: () => void;
}) {
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [readback, setReadback] = useState<SapPublishView | null | "loading">("loading");
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    api.GET("/requests/{req_id}", { path: { req_id: reqId } }).then(
      async (d) => {
        if (!current) return;
        setDetail(d);
        const published = d.state === "ACTIVE" || d.state === "PUBLISHED_INACTIVE";
        const view = published ? await readbackFor(d) : null;
        if (current) setReadback(view);
      },
      (e: unknown) => current && setError(explain(e, "Loading the request")),
    );
    return () => {
      current = false;
    };
  }, [reqId]);

  async function publish() {
    setPublishing(true);
    setPublishError(null);
    try {
      const d = await api.POST("/requests/{req_id}/publish", { path: { req_id: reqId } });
      setDetail(d);
      setReadback("loading");
      const view = await readbackFor(d);
      setReadback(view);
      toast.success(`Published to SAP: ${d.title}`, {
        description: view
          ? view.all_match
            ? `${view.sap_code} is live. Every field SAP saved matches what we sent.`
            : `${view.sap_code} was created, but some fields differ. Check the table.`
          : "The record was sent to SAP.",
      });
      announceWorkflowChange();
      onPublished();
    } catch (e) {
      setPublishError(explain(e, "Publishing"));
    } finally {
      setPublishing(false);
    }
  }

  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!detail) return <Skeleton className="h-96 w-full" />;

  const published = detail.state === "ACTIVE" || detail.state === "PUBLISHED_INACTIVE";
  const allowed = (detail.allowed_actions ?? []).includes("publish");

  return (
    <section className="flex flex-col gap-6 rounded-xl border p-6" data-testid="publish-pane">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <p className="text-sm text-muted-foreground">
            {detail.req_id}, {requestContext(detail)}, asked by {detail.requestor_name}
          </p>
          <h2 className="text-xl font-semibold tracking-tight">{detail.title}</h2>
          <div className="flex items-center gap-2">
            <StateBadge state={detail.state} />
            <Link
              href={`/requests/${detail.req_id}`}
              className="text-sm text-muted-foreground underline underline-offset-4"
            >
              Full status and history
            </Link>
          </div>
        </div>
      </div>

      {!published && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h3 className="text-sm font-semibold">What will be sent</h3>
            <p className="text-xs text-muted-foreground">
              One call to SAP Business One:{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono">
                POST /b1s/v2/{RESOURCE[detail.domain]}
              </code>
              . The record is created inactive, read back and checked, then switched on.
            </p>
          </div>
          <RequestFields detail={detail} />
          <div className="flex flex-col gap-2 border-t pt-5">
            <div className="flex items-center gap-4">
              <Button
                onClick={() => void publish()}
                disabled={publishing || !canPublish}
                data-testid="publish"
              >
                {publishing ? (
                  <Loader2 className="animate-spin" data-icon="inline-start" />
                ) : (
                  <SendHorizontal data-icon="inline-start" />
                )}
                Publish to SAP
              </Button>
              <p className="text-sm text-muted-foreground">
                {!canPublish
                  ? "Switch to Priya (master-data analyst) to publish."
                  : allowed
                    ? "All approvals are in."
                    : "The server will check that you are allowed to publish this one."}
              </p>
            </div>
            {publishError && (
              <p className="text-sm text-destructive" role="alert" data-testid="publish-error">
                {publishError}
              </p>
            )}
          </div>
        </div>
      )}

      {published &&
        (readback === "loading" ? (
          <Skeleton className="h-64 w-full" />
        ) : readback ? (
          <SapReadback view={readback} />
        ) : (
          <div className="flex flex-col gap-3">
            <p className="flex items-center gap-2 text-sm">
              <CircleCheck className="size-4 text-success" />
              Sent to SAP on {formatSgt(detail.updated_at)} (demo clock).
            </p>
            <ReadbackUnavailable />
            <h3 className="pt-2 text-sm font-semibold">What was sent</h3>
            <RequestFields detail={detail} />
          </div>
        ))}
    </section>
  );
}
