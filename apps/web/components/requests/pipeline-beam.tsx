"use client";

/**
 * The request's journey in one strip (D-023 #4): Email -> Read by AI -> Golden record ->
 * Approvals -> In SAP. Every node is derived in the browser from `RequestDetail`; nothing here
 * asks the API for more. The beam into the step that is happening now sweeps once (at most
 * 400 ms) when the page opens and again only when that segment changes; it never loops and is
 * left out entirely under reduced motion.
 */
import { Check, Database, FileCheck2, Mail, Pause, Sparkles, Users, X } from "lucide-react";
import { type RefObject, useRef } from "react";

import { AnimatedBeam } from "@/components/ui/animated-beam";
import type { Schema } from "@/lib/api/client";
import { usePrefersReducedMotion } from "@/lib/use-reduced-motion";
import { cn } from "@/lib/utils";

type RequestDetail = Schema<"RequestDetail">;

/** "not_needed": the step does not apply to this kind of request (no duplicate check for items),
 * shown as a neutral check so the journey still reads as complete. "skipped": it was bypassed. */
export type NodeState =
  | "done"
  | "current"
  | "paused"
  | "waiting"
  | "skipped"
  | "not_needed"
  | "rejected";
type NodeId = "email" | "ai" | "golden" | "approvals" | "sap";
type PipelineNode = { id: NodeId; label: string; state: NodeState; caption: string };

/** How long one beam sweep takes. Kept under the 400 ms motion budget. */
export const BEAM_MS = 350;

const STATE_WORD: Record<NodeState, string> = {
  done: "Done",
  current: "Happening now",
  paused: "Paused",
  waiting: "Not started",
  skipped: "Not needed",
  not_needed: "Not needed",
  rejected: "Stopped",
};

const ICON = { email: Mail, ai: Sparkles, golden: FileCheck2, approvals: Users, sap: Database };

function count(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

/** The five steps and where this request is on each, in plain English. */
export function pipelineNodes(d: RequestDetail): PipelineNode[] {
  const s = d.state;
  const fromEmail = !!d.source_email_id;
  const linked = s === "LINKED_TO_EXISTING";
  const draft = s === "DRAFT";
  const approved = s === "APPROVED" || s === "PUBLISHED_INACTIVE" || s === "ACTIVE";

  const email: PipelineNode = fromEmail
    ? { id: "email", label: "Email", state: "done", caption: "From an email" }
    : { id: "email", label: "Email", state: "skipped", caption: "Typed into the form" };

  const quotes = Object.keys(d.prefill_quotes ?? {}).length;
  const ai: PipelineNode = fromEmail
    ? {
        id: "ai",
        label: "Read by AI",
        state: "done",
        caption: quotes
          ? `${count(quotes, "detail", "details")} pre-filled`
          : "Nothing to pre-fill",
      }
    : { id: "ai", label: "Read by AI", state: "skipped", caption: "No email to read" };

  // The duplicate check runs for customers and vendors only (the API's submit path).
  const golden: PipelineNode = { id: "golden", label: "Golden record", state: "done", caption: "" };
  if (d.domain === "item" || d.domain === "cost_center")
    Object.assign(golden, {
      state: "not_needed",
      caption: `Not needed for ${d.domain === "item" ? "items" : "cost centers"}`,
    });
  else if (draft) Object.assign(golden, { state: "current", caption: "Not checked yet" });
  else if (linked)
    golden.caption = `Linked to ${d.linked_card_name ?? d.linked_card_code ?? "an existing record"}`;
  else if (d.dedup_decision?.action === "not_duplicate")
    golden.caption = "New record, checked by a person";
  // A "possible" match never blocks submit and leaves no record, so don't claim "none found".
  else golden.caption = "Nothing needed a decision";

  // The publish step is a task too (the MDM analyst's); it belongs to "In SAP", not here.
  const tasks = (d.stages ?? [])
    .flatMap((st) => st.tasks)
    .filter((t) => t.role !== "mdm_analyst" && t.status !== "cancelled");
  const yes = tasks.filter((t) => t.status === "approved").length;
  const approvals: PipelineNode = {
    id: "approvals",
    label: "Approvals",
    state: "waiting",
    caption: "",
  };
  if (draft) approvals.caption = "Start when it is submitted";
  else if (linked) Object.assign(approvals, { state: "skipped", caption: "Existing record used" });
  else if (s === "REJECTED") {
    const by = tasks.find((t) => t.status === "rejected")?.assignee_name;
    Object.assign(approvals, { state: "rejected", caption: by ? `Rejected by ${by}` : "Rejected" });
  } else if (approved) Object.assign(approvals, { state: "done", caption: "All approved" });
  else if (s === "INFO_REQUESTED")
    // The ball is with the requestor: the approvals wait for an answer, nothing is moving.
    Object.assign(approvals, {
      state: "paused",
      caption: `${yes} of ${tasks.length} approved, paused for a question`,
    });
  else
    Object.assign(approvals, { state: "current", caption: `${yes} of ${tasks.length} approved` });

  const code = d.sap_publish?.sap_code;
  const sap: PipelineNode = { id: "sap", label: "In SAP", state: "waiting", caption: "Not yet" };
  if (s === "ACTIVE")
    Object.assign(sap, { state: "done", caption: code ? `Live in SAP as ${code}` : "Live in SAP" });
  else if (s === "PUBLISHED_INACTIVE")
    Object.assign(sap, { state: "current", caption: "Sent to SAP, confirming it saved" });
  else if (s === "APPROVED")
    Object.assign(sap, { state: "current", caption: "Ready, waiting to be published" });
  else if (linked)
    Object.assign(sap, {
      state: "done",
      caption: d.linked_card_code ? `Already in SAP as ${d.linked_card_code}` : "Already in SAP",
    });
  else if (s === "REJECTED") sap.caption = "Not sent";

  return [email, ai, golden, approvals, sap];
}

type SegmentKind = "lit" | "flow" | "paused" | "skip" | "stopped" | "dim";

/** What the line between two neighbouring steps looks like. */
function segmentKind(from: NodeState, to: NodeState): SegmentKind {
  // A step that does not apply is passed straight through, like a finished one.
  const a = from === "not_needed" ? "done" : from;
  const b = to === "not_needed" ? "done" : to;
  if (a === "done" && b === "done") return "lit";
  if (a === "done" && b === "current") return "flow";
  if (a === "done" && b === "paused") return "paused";
  if (a === "done" && b === "rejected") return "stopped";
  if (a === "skipped" || b === "skipped") return "skip";
  return "dim";
}

const LINE_CLASS: Record<SegmentKind, string> = {
  lit: "border-primary",
  flow: "border-primary/35",
  paused: "border-dashed border-warning",
  stopped: "border-destructive/50",
  skip: "border-dashed border-border",
  dim: "border-border",
};

export function PipelineBeam({ detail }: { detail: RequestDetail }) {
  const nodes = pipelineNodes(detail);
  const reduced = usePrefersReducedMotion();
  const r0 = useRef<HTMLDivElement>(null);
  const r1 = useRef<HTMLDivElement>(null);
  const r2 = useRef<HTMLDivElement>(null);
  const r3 = useRef<HTMLDivElement>(null);
  const r4 = useRef<HTMLDivElement>(null);
  const refs = [r0, r1, r2, r3, r4];

  return (
    <section
      className="relative rounded-xl border bg-card px-4 py-4"
      data-testid="pipeline-beam"
      data-reduced-motion={reduced ? "true" : "false"}
    >
      <div className="pointer-events-none absolute inset-x-4 top-4 h-9" aria-hidden>
        {nodes.slice(1).map((b, i) => {
          const kind = segmentKind(nodes[i].state, b.state);
          return (
            <Segment
              // A new key replays the sweep: only when this segment's look actually changes.
              key={`${nodes[i].id}-${kind}`}
              index={i}
              kind={kind}
              sweep={kind === "flow" && !reduced}
              fromRef={refs[i]}
              toRef={refs[i + 1]}
            />
          );
        })}
      </div>
      <ol aria-label="Where this request is" className="relative grid grid-cols-5">
        {nodes.map((n, i) => (
          <PipelineStep key={n.id} node={n} discRef={refs[i]} />
        ))}
      </ol>
    </section>
  );
}

function Segment({
  index,
  kind,
  sweep,
  fromRef,
  toRef,
}: {
  index: number;
  kind: SegmentKind;
  sweep: boolean;
  fromRef: RefObject<HTMLDivElement | null>;
  toRef: RefObject<HTMLDivElement | null>;
}) {
  const box = useRef<HTMLDivElement>(null);
  return (
    <div
      ref={box}
      className="absolute top-0 h-9 w-1/5"
      style={{ left: `${(index + 0.5) * 20}%` }}
      data-testid="beam-segment"
      data-kind={kind}
      data-sweep={sweep ? "true" : "false"}
      data-duration-ms={sweep ? BEAM_MS : 0}
    >
      <div
        className={cn("absolute inset-x-0 top-1/2 -translate-y-1/2 border-t-2", LINE_CLASS[kind])}
      />
      {sweep && (
        <AnimatedBeam
          containerRef={box}
          fromRef={fromRef}
          toRef={toRef}
          duration={BEAM_MS / 1000}
          repeat={0}
          pathOpacity={0}
          pathWidth={2}
          gradientStartColor="var(--primary)"
          gradientStopColor="var(--success)"
        />
      )}
    </div>
  );
}

const DISC_CLASS: Record<NodeState, string> = {
  done: "border-primary bg-primary text-primary-foreground",
  current: "border-primary bg-card text-primary ring-4 ring-primary/15",
  paused: "border-warning bg-card text-warning-foreground",
  waiting: "border-border bg-muted text-muted-foreground",
  skipped: "border-dashed border-muted-foreground/40 bg-card text-muted-foreground/70",
  not_needed: "border-muted-foreground/50 bg-card text-muted-foreground",
  rejected: "border-destructive bg-destructive text-destructive-foreground",
};

function PipelineStep({
  node: n,
  discRef,
}: {
  node: PipelineNode;
  discRef: RefObject<HTMLDivElement | null>;
}) {
  const Icon = n.state === "rejected" ? X : n.state === "paused" ? Pause : ICON[n.id];
  const quiet = n.state === "waiting" || n.state === "skipped";
  return (
    <li
      className="flex min-w-0 flex-col items-center gap-1.5 px-2 text-center"
      data-testid="beam-node"
      data-node={n.id}
      data-state={n.state}
    >
      <div
        ref={discRef}
        className={cn(
          "relative z-10 flex size-9 items-center justify-center rounded-full border-2 transition-[background-color,border-color,color,box-shadow] duration-300",
          DISC_CLASS[n.state],
        )}
      >
        <Icon className="size-4" aria-hidden />
        {(n.state === "done" || n.state === "not_needed") && (
          <span
            className={cn(
              "absolute -right-1 -bottom-1 flex size-4 items-center justify-center rounded-full text-white ring-2 ring-card",
              n.state === "done" ? "bg-success" : "bg-muted-foreground/70",
            )}
          >
            <Check className="size-2.5" strokeWidth={3} aria-hidden />
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-col items-center">
        <span className={cn("text-sm font-medium leading-tight", quiet && "text-muted-foreground")}>
          <span className="sr-only">{STATE_WORD[n.state]}: </span>
          {n.label}
        </span>
        <span
          className={cn(
            "w-full truncate text-xs leading-tight text-muted-foreground",
            n.state === "rejected" && "text-destructive",
            n.state === "current" && "text-foreground",
            n.state === "paused" && "text-warning-foreground",
          )}
          title={n.caption}
          data-testid="beam-caption"
        >
          {n.caption}
        </span>
      </div>
    </li>
  );
}
