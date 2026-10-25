"use client";

/**
 * The right-hand panel of an opened email: what the AI read. It renders a
 * `ReadView`, which is either a finished Interpretation or one being built up
 * step by step by the live trace (D-023 #3), so both look the same.
 */
import {
  CloudOff,
  FilePlus2,
  History,
  Loader2,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  UserRoundSearch,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Schema } from "@/lib/api/client";
import {
  CATEGORY_HELP,
  CATEGORY_TEXT,
  CATEGORY_WITH_ARTICLE,
  type Category,
  type Interpretation,
  keyLabel,
  valueText,
} from "@/lib/emails";
import type { InterpretStep, TraceSource } from "@/lib/interpret-stream";
import { cn } from "@/lib/utils";

type Verdict = Pick<Interpretation, "category" | "confidence" | "method" | "ai_message"> & {
  needs_review: boolean;
};

/** What the panel shows. While the trace runs, the parts fill in as their steps arrive. */
export type ReadView = {
  fields: Schema<"QuotedValue">[];
  lines: Schema<"OrderLine">[];
  bankStripped: boolean;
  verdict: Verdict | null;
  missing: { fields: string[]; questions: string[] } | null;
  injection: boolean;
};

export const EMPTY_VIEW: ReadView = {
  fields: [],
  lines: [],
  bankStripped: false,
  verdict: null,
  missing: null,
  injection: false,
};

export function viewOf(read: Interpretation): ReadView {
  return {
    fields: read.fields ?? [],
    lines: read.lines ?? [],
    bankStripped: !!read.bank_details_stripped,
    verdict: {
      category: read.category,
      confidence: read.confidence,
      method: read.method,
      ai_message: read.ai_message,
      needs_review: !!read.needs_review,
    },
    missing: {
      fields: read.missing_fields ?? [],
      questions: read.questions_for_requester ?? [],
    },
    injection: !!read.injection_suspected,
  };
}

/** One trace step folded into the view. `start` and `done` change nothing here. */
export function applyStep(view: ReadView, step: InterpretStep): ReadView {
  switch (step.kind) {
    case "bank_stripped":
      return { ...view, bankStripped: true };
    case "field":
      return { ...view, fields: [...view.fields, step.field] };
    case "line":
      return { ...view, lines: [...view.lines, step.line] };
    case "category":
      return {
        ...view,
        verdict: {
          category: step.category,
          confidence: step.confidence,
          method: step.method,
          needs_review: step.needs_review,
        },
      };
    case "missing":
      return {
        ...view,
        missing: { fields: step.missing_fields, questions: step.questions_for_requester },
      };
    case "injection":
      return { ...view, injection: true };
    default:
      return view;
  }
}

/** The highlight keys of the quotes in a view: field keys, then `line-{i}`. */
export function quotesOf(view: ReadView): { key: string; quote: string }[] {
  return [
    ...view.fields.map((f) => ({ key: f.key, quote: f.source_quote })),
    ...view.lines.map((l, i) => ({ key: `line-${i}`, quote: l.source_quote })),
  ];
}

/** Fits half the panel's width: a short label and a short value (a tax ID, a city, a country). */
function isShort(f: Schema<"QuotedValue">): boolean {
  return keyLabel(f.key).length <= 18 && valueText(f.value).length <= 16;
}

export function CategoryChip({ category }: { category: Category }) {
  return (
    <Badge
      variant="secondary"
      className={cn(category === "mdm_request" && "bg-foreground text-background")}
      data-testid="category-chip"
      data-category={category}
    >
      {CATEGORY_TEXT[category]}
    </Badge>
  );
}

export const REPLAY_HELP =
  "This answer was recorded from the AI earlier, for this exact email. Replaying it makes the " +
  "demo behave the same every time, even without the internet. Every detail still comes from " +
  "words in the email.";

/** The row above the reading: where the answer came from, and a way to watch it again. */
export function TraceBar({
  source,
  streaming,
  onReplay,
}: {
  source: TraceSource | null;
  streaming: boolean;
  onReplay: () => void;
}) {
  return (
    <div className="flex h-7 items-center justify-between gap-2">
      {source === "replay" ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className="cursor-help text-muted-foreground"
              data-testid="replay-badge"
              asChild
            >
              <button type="button">
                <History data-icon="inline-start" />
                Replaying a recorded AI response
              </button>
            </Badge>
          </TooltipTrigger>
          <TooltipContent className="max-w-72" data-testid="replay-help">
            {REPLAY_HELP}
          </TooltipContent>
        </Tooltip>
      ) : (
        <span />
      )}
      {!streaming && (
        <Button
          variant="ghost"
          size="xs"
          className="text-muted-foreground"
          onClick={onReplay}
          data-testid="replay-trace"
        >
          <RotateCcw data-icon="inline-start" />
          Watch again
        </Button>
      )}
    </div>
  );
}

const ENTER = "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-300";

/** The live line under the reading while it fills in. A replay must not sound like a live call. */
export function traceStatusText(source: TraceSource | null): string {
  switch (source) {
    case "replay":
      return "Showing what the AI read…";
    case "keyword_fallback":
      return "The keyword rules are sorting this email…";
    case "live":
      return "The AI is reading this email…";
    default:
      return "Opening the AI's reading…";
  }
}

export function Reading({
  view,
  source,
  streaming,
  focusKey,
  onFocusKey,
  onCreate,
}: {
  view: ReadView;
  /** Where the answer comes from; only changes the wording of the status line. */
  source: TraceSource | null;
  /** True while the trace is still arriving: unrevealed parts show placeholders. */
  streaming: boolean;
  focusKey: string | null;
  onFocusKey: (key: string) => void;
  onCreate: () => void;
}) {
  const { fields, lines, verdict, missing } = view;
  const questions = missing?.questions ?? [];
  const missingFields = missing?.fields ?? [];
  const enter = streaming ? ENTER : undefined;
  // Shown right under "Details found", so it is on screen without scrolling (D-021 beat 4).
  const bankNotice = view.bankStripped ? (
    <p
      className={cn(
        "flex items-start gap-1.5 rounded-md bg-success/10 px-2 py-1.5 text-xs text-foreground",
        enter,
      )}
      data-testid="bank-stripped"
    >
      <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-success" />
      Bank details in this email were removed before the AI read it. They are never sent to the AI,
      and only Finance can see them.
    </p>
  ) : null;
  // The heading shows as soon as anything for it arrives, so it never jumps in above an already
  // visible bank notice, and it stays when bank details were the only thing found.
  const showDetails = fields.length > 0 || view.bankStripped;

  return (
    <>
      {verdict ? (
        <div className={cn("flex flex-col gap-2", enter)}>
          <div className="flex flex-wrap items-center gap-2">
            <CategoryChip category={verdict.category} />
            {verdict.method === "keyword_fallback" && (
              <Badge variant="outline" data-testid="ai-offline">
                <CloudOff data-icon="inline-start" />
                AI offline
              </Badge>
            )}
            {verdict.needs_review && (
              <Badge
                variant="secondary"
                className="bg-warning/15 text-warning-foreground"
                data-testid="needs-review"
              >
                <UserRoundSearch data-icon="inline-start" />
                Needs human review
              </Badge>
            )}
          </div>
          <p className="text-sm" data-testid="confidence">
            {/* No percentage: the model rates itself 90% on most emails, which says nothing. */}
            {verdict.method === "keyword_fallback" ? "The keyword rules read" : "The AI reads"} this
            as {CATEGORY_WITH_ARTICLE[verdict.category]}.
            <span className="text-muted-foreground">
              {" "}
              {view.injection
                ? "The email seems to give the AI orders, so a person sorts it."
                : verdict.needs_review
                  ? "The AI wasn't sure, so a person sorts it."
                  : CATEGORY_HELP[verdict.category]}
            </span>
          </p>
          {verdict.method === "keyword_fallback" && (
            <p className="text-xs text-muted-foreground">
              {verdict.ai_message ?? "AI offline: showing the keyword rules' best guess"}.
            </p>
          )}
        </div>
      ) : (
        // Holds the category's place while the AI is still reading, so nothing below jumps.
        <div className="flex flex-col gap-2" aria-hidden>
          <Skeleton className="h-5 w-32 rounded-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}

      {view.injection && (
        <div
          className={cn(
            "flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm",
            enter,
          )}
          data-testid="injection-warning"
          role="alert"
        >
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
          <p>
            <span className="font-medium">Possible hidden instructions.</span> This email seems to
            give orders to the AI. They were ignored: an email can never change approvers, bank
            details or credit terms. A person should check it.
          </p>
        </div>
      )}

      {showDetails && (
        <div className="flex flex-col gap-1.5">
          <h3 className="text-sm font-semibold">Details found</h3>
          {bankNotice}
          {!streaming && fields.length === 0 && (
            <p className="text-sm text-muted-foreground" data-testid="no-other-details">
              No other details were found in this email.
            </p>
          )}
          {/* Two columns: short details (a tax ID, a city) share a row, long ones take the full
              width, in the order the AI found them. Keeps the action below on screen. */}
          <ul className="grid grid-cols-2 gap-x-1 gap-y-0.5" data-testid="extracted-fields">
            {fields.map((f) => (
              <li key={f.key} className={cn(isShort(f) ? "col-span-1" : "col-span-2", enter)}>
                <button
                  type="button"
                  onMouseEnter={() => onFocusKey(f.key)}
                  onFocus={() => onFocusKey(f.key)}
                  onClick={() => onFocusKey(f.key)}
                  className={cn(
                    "flex w-full flex-col rounded-md px-2 py-1 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    focusKey === f.key ? "bg-warning/20" : "hover:bg-muted",
                  )}
                  data-testid={`extracted-${f.key}`}
                >
                  <span className="text-xs leading-4 text-muted-foreground">{keyLabel(f.key)}</span>
                  <span className="text-sm leading-5 font-medium break-words">
                    {valueText(f.value)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {!streaming && fields.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Point at a detail to see the words it came from, highlighted in the email.
            </p>
          )}
        </div>
      )}

      {lines.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">Products and quantities</h3>
          <ul className="flex flex-col gap-1 text-sm" data-testid="order-lines">
            {lines.map((l, i) => (
              <li key={i} className={enter}>
                <button
                  type="button"
                  onMouseEnter={() => onFocusKey(`line-${i}`)}
                  onFocus={() => onFocusKey(`line-${i}`)}
                  className={cn(
                    "flex w-full items-baseline justify-between gap-3 rounded-md px-2 py-1 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    focusKey === `line-${i}` ? "bg-warning/20" : "hover:bg-muted",
                  )}
                >
                  <span>
                    {l.product_text ?? l.item_code}
                    {l.item_code && l.product_text && (
                      <span className="ml-1.5 text-xs text-muted-foreground">{l.item_code}</span>
                    )}
                  </span>
                  <span className="tabular-nums">{l.qty ?? "?"}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(missingFields.length > 0 || questions.length > 0) && (
        <div className={cn("flex flex-col gap-2", enter)} data-testid="missing-fields">
          <h3 className="text-sm font-semibold">Missing from the email</h3>
          {questions.length > 0 ? (
            <ul className="flex list-disc flex-col gap-1 pl-5 text-sm">
              {questions.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm">{missingFields.map(keyLabel).join(", ")}</p>
          )}
          <p className="text-xs text-muted-foreground">
            The form asks the requestor for these before anything reaches an approver.
          </p>
        </div>
      )}

      {streaming ? (
        <p
          className="flex items-center gap-2 text-sm text-muted-foreground"
          role="status"
          data-testid="trace-status"
        >
          <Loader2 className="size-4 motion-safe:animate-spin" />
          {traceStatusText(source)}
        </p>
      ) : (
        verdict?.category === "mdm_request" && (
          // Sticks to the bottom of the screen while the reading runs below the fold, so the
          // next step is always in view; it settles in place once the panel's end scrolls up.
          <div
            className="sticky bottom-0 z-10 flex flex-col gap-1.5 border-t bg-card pt-3 pb-4"
            data-testid="create-request-bar"
          >
            <Button onClick={onCreate} data-testid="create-request">
              <FilePlus2 data-icon="inline-start" />
              Create request from this email
            </Button>
            <p className="text-xs text-muted-foreground">
              Opens the request form filled in with these details, each one showing where it came
              from. Nothing is submitted until you check it.
            </p>
          </div>
        )
      )}
    </>
  );
}
