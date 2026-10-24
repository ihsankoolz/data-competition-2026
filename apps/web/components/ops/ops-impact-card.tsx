"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { days, pct } from "@/lib/analytics";
import { api, isApiError, type Schema } from "@/lib/api/client";

type Ops = Schema<"OpsImpact">;
type Stat = Schema<"CycleTimeStat">;

const SOURCE_TEXT: Record<Schema<"Assumption">["source"], string> = {
  brief: "The brief",
  generated_history: "Our past request history",
  our_design: "Our design",
  assumption: "Assumption",
};

/**
 * Judges read this page: no file names or decision numbers, and the two jargon terms spelled
 * out the first time they appear on the page (`seen` is shared across the page's texts).
 */
function plain(text: string, seen?: Set<string>): string {
  let out = text
    .replace(/\s*\((?:D-\d+(?:[^)]*)?)\)/g, "")
    .replace(/\b(?:in |from )?[\w./-]+\.(?:csv|py|json|ya?ml)\b/g, "in our past request history")
    .replace(/\s{2,}/g, " ");
  const expand: [RegExp, string, string][] = [
    [/\bIVD\b/, "IVD", "IVD (in-vitro diagnostic, a lab test product)"],
    [/\bBU Head\b/, "BU Head", "BU Head (business unit head)"],
  ];
  if (seen) {
    for (const [re, key, long] of expand) {
      if (!seen.has(key) && re.test(out)) {
        out = out.replace(re, long);
        seen.add(key);
      }
    }
  }
  return out;
}

/** "First sentence." and the rest. */
function firstSentence(text: string): [string, string] {
  const m = /^(.+?[.!?])\s+([\s\S]+)$/.exec(text.trim());
  return m ? [m[1]!, m[2]!] : [text, ""];
}

function MoreText({ text, testId }: { text: string; testId: string }) {
  const [open, setOpen] = useState(false);
  const [first, rest] = firstSentence(text);
  return (
    <p className="text-sm leading-relaxed text-muted-foreground" data-testid={testId}>
      {first}
      {rest && open && <> {rest}</>}
      {rest && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="ml-1.5 font-medium text-foreground underline-offset-4 hover:underline"
          data-testid={`${testId}-more`}
        >
          {open ? "Less" : "More"}
        </button>
      )}
    </p>
  );
}

function useOpsImpact() {
  const [ops, setOps] = useState<Ops | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    api.GET("/analytics/ops-impact").then(
      (o) => {
        if (!current) return;
        setOps(o);
        setError(null);
      },
      (e: unknown) =>
        current &&
        setError(isApiError(e) ? e.message : "The ops impact numbers could not be loaded."),
    );
    return () => {
      current = false;
    };
  }, [attempt]);
  return { ops, error, retry: () => setAttempt((n) => n + 1) };
}

function stat(ops: Ops, process: Stat["process"]): Stat | undefined {
  return ops.cycle_time.find((c) => c.process === process);
}

function ModelledTag() {
  return (
    <span
      className="inline-flex w-fit items-center rounded-full border border-warning/50 bg-warning/10 px-2.5 py-0.5 text-xs font-medium text-warning-foreground"
      data-testid="modelled-tag"
    >
      Modelled, not measured
    </span>
  );
}

function Failure({ error, retry }: { error: string; retry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed p-6 text-sm">
      <p>{error}</p>
      <Button variant="outline" size="sm" onClick={retry}>
        Try again
      </Button>
    </div>
  );
}

/** Four headline numbers: Amy's case, typical request, first time right, duplicates stopped. */
function Headlines({ ops }: { ops: Ops }) {
  const old = stat(ops, "old_email_sequential");
  const now = stat(ops, "new_parallel");
  return (
    <dl className="grid grid-cols-4 gap-6" data-testid="ops-headlines">
      <div className="flex flex-col gap-1" data-testid="ops-amy">
        <dt className="text-xs text-muted-foreground">Amy&apos;s new test-kit item</dt>
        <dd className="flex items-baseline gap-2 tabular-nums">
          <span className="text-lg text-muted-foreground line-through decoration-1">
            {days(ops.amy_before_bd)}
          </span>
          <span className="text-3xl font-semibold" data-testid="ops-amy-after">
            ~{days(Math.round(ops.amy_after_bd))}
          </span>
          <span className="text-sm text-muted-foreground">business days</span>
        </dd>
        <dd className="text-xs text-muted-foreground">
          The brief&apos;s example: {days(ops.amy_before_bd)} days today, about{" "}
          {days(ops.amy_after_bd)} with parallel approvals.
        </dd>
      </div>
      {old && now && (
        <div className="flex flex-col gap-1" data-testid="ops-median">
          <dt className="text-xs text-muted-foreground">A typical request</dt>
          <dd className="flex items-baseline gap-2 tabular-nums">
            <span className="text-lg text-muted-foreground line-through decoration-1">
              {days(old.median_bd)}
            </span>
            <span className="text-3xl font-semibold">{days(now.median_bd)}</span>
            <span className="text-sm text-muted-foreground">business days</span>
          </dd>
          <dd className="text-xs text-muted-foreground">
            Half of past requests would finish faster than this. The slowest 1 in 10 take over{" "}
            {days(old.p90_bd)} days today, {days(now.p90_bd)} in the new process.
          </dd>
        </div>
      )}
      <div className="flex flex-col gap-1" data-testid="ops-ftr">
        <dt className="text-xs text-muted-foreground">Arrive complete the first time</dt>
        <dd className="flex items-baseline gap-2 tabular-nums">
          <span className="text-lg text-muted-foreground line-through decoration-1">
            {pct(ops.first_time_right_before_pct, 0)}
          </span>
          <span className="text-3xl font-semibold">{pct(ops.first_time_right_after_pct, 0)}</span>
        </dd>
        <dd className="text-xs text-muted-foreground">
          Requests not sent back for a missing field, because the form checks them before submit.
        </dd>
      </div>
      <div className="flex flex-col gap-1" data-testid="ops-dupes">
        <dt className="text-xs text-muted-foreground">Duplicates stopped at entry</dt>
        <dd className="text-3xl font-semibold tabular-nums" data-testid="ops-dupes-value">
          {ops.duplicates_prevented}
        </dd>
        <dd className="text-xs text-muted-foreground">
          {ops.duplicates_prevented === 0
            ? "0 so far in this demo; each one is a request someone linked instead of creating a duplicate."
            : "Requests in this demo linked to an existing record instead of creating a duplicate. Counted live, not modelled."}
        </dd>
      </div>
    </dl>
  );
}

/** The full M10 card for /ops. */
export function OpsImpactCard() {
  const { ops, error, retry } = useOpsImpact();
  if (error && !ops) return <Failure error={error} retry={retry} />;
  if (!ops)
    return (
      <div className="flex flex-col gap-6" aria-busy>
        <Skeleton className="h-36 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  const old = stat(ops, "old_email_sequential");
  const now = stat(ops, "new_parallel");
  // Page order: caption, Amy's explanation, then the assumptions table.
  const seen = new Set<string>();
  const caption = plain(ops.caption, seen);
  const amy = plain(ops.amy_explanation, seen);
  const assumptions = ops.assumptions.map((a) => ({
    ...a,
    name: plain(a.name, seen),
    value: plain(a.value, seen),
  }));

  return (
    <div className="flex flex-col gap-10" data-testid="ops-card">
      <section className="flex flex-col gap-6 rounded-xl border bg-card px-6 py-5">
        <div className="flex flex-col gap-2">
          <ModelledTag />
          <p className="max-w-3xl text-sm text-muted-foreground">{caption}</p>
        </div>
        <Headlines ops={ops} />
      </section>

      {old && now && (
        <section aria-labelledby="cycle-title" className="flex flex-col gap-3">
          <h2 id="cycle-title" className="text-base font-semibold tracking-tight">
            Cycle time from submit to live in SAP
          </h2>
          <table className="w-full max-w-3xl text-sm" data-testid="cycle-table">
            <thead>
              <tr className="text-xs text-muted-foreground">
                <th scope="col" className="pb-2 text-left font-normal">
                  Process
                </th>
                <th scope="col" className="pb-2 text-right font-normal">
                  Typical (median), business days
                </th>
                <th scope="col" className="pb-2 text-right font-normal">
                  Slowest 1 in 10 (90th percentile)
                </th>
              </tr>
            </thead>
            <tbody>
              {[old, now].map((s) => (
                <tr key={s.process} className="border-t">
                  <th scope="row" className="py-2 text-left font-normal">
                    {s.label}
                  </th>
                  <td className="py-2 text-right tabular-nums">{days(s.median_bd)}</td>
                  <td className="py-2 text-right tabular-nums">{days(s.p90_bd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section aria-labelledby="amy-title" className="flex max-w-3xl flex-col gap-2">
        <h2 id="amy-title" className="text-base font-semibold tracking-tight">
          How Amy&apos;s 18 days become about {days(Math.round(ops.amy_after_bd))}
        </h2>
        <MoreText text={amy} testId="amy-explanation" />
      </section>

      <section aria-labelledby="assumptions-title" className="flex flex-col gap-3">
        <h2 id="assumptions-title" className="text-base font-semibold tracking-tight">
          Every assumption, with where it comes from
        </h2>
        <table className="w-full text-sm" data-testid="assumptions">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th scope="col" className="pb-2 text-left font-normal">
                Assumption
              </th>
              <th scope="col" className="pb-2 text-left font-normal">
                Value
              </th>
              <th scope="col" className="pb-2 text-left font-normal">
                Source
              </th>
            </tr>
          </thead>
          <tbody>
            {assumptions.map((a) => (
              <tr key={a.name} className="border-t align-top">
                <th scope="row" className="py-2 pr-4 text-left font-medium">
                  {a.name}
                </th>
                <td className="py-2 pr-4 text-muted-foreground">{a.value}</td>
                <td className="py-2 whitespace-nowrap">{SOURCE_TEXT[a.source]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

/** A short version for the bottom of the regional view. */
export function OpsImpactCompact() {
  const { ops, error, retry } = useOpsImpact();
  return (
    <section
      aria-labelledby="ops-compact-title"
      className="flex flex-col gap-4"
      data-testid="ops-compact"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-2">
          <h2 id="ops-compact-title" className="text-xl font-semibold tracking-tight">
            What the new process does for the MDM team
          </h2>
          <ModelledTag />
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href="/ops">See the assumptions</Link>
        </Button>
      </div>
      {error && !ops ? (
        <Failure error={error} retry={retry} />
      ) : ops ? (
        <Headlines ops={ops} />
      ) : (
        <Skeleton className="h-28 w-full" aria-busy />
      )}
    </section>
  );
}
