"use client";

import { Loader2, Paperclip, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  applyStep,
  CategoryChip,
  EMPTY_VIEW,
  quotesOf,
  type ReadView,
  Reading,
  TraceBar,
  viewOf,
} from "@/components/inbox/ai-reading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useActingUserId } from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import {
  CATEGORIES,
  CATEGORY_HELP,
  CATEGORY_TEXT,
  type Category,
  highlight,
  type Interpretation,
} from "@/lib/emails";
import { formatSgt } from "@/lib/format";
import { interpretWithTrace, type TraceResult, type TraceSource } from "@/lib/interpret-stream";
import { prefersReducedMotion, usePrefersReducedMotion } from "@/lib/use-reduced-motion";
import { cn } from "@/lib/utils";

type EmailSummary = Schema<"EmailSummary">;
type EmailDetail = Schema<"EmailDetail">;

const PARALLEL_READS = 6;

function explain(e: unknown, what: string): string {
  if (isApiError(e) && e.status === 501)
    return `${what} isn't available right now. Try again in a moment.`;
  return isApiError(e) ? e.message : `${what} did not work. Please try again.`;
}

export function MessyInbox() {
  const router = useRouter();
  const actingUser = useActingUserId();
  const [emails, setEmails] = useState<EmailSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [reads, setReads] = useState<Record<string, Interpretation>>({});
  // Where each traced read came from (a recorded replay, live, or the keyword rules).
  const [sources, setSources] = useState<Record<string, TraceSource>>({});
  const [reading, setReading] = useState<Set<string>>(new Set());
  const [readError, setReadError] = useState<string | null>(null);
  const [sortingAll, setSortingAll] = useState(false);
  const [filter, setFilter] = useState<Category | "all">("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!actingUser) return;
    let current = true;
    api.GET("/emails").then(
      (list) => {
        if (!current) return;
        setEmails(list);
        setError(null);
      },
      (e: unknown) => current && setError(explain(e, "Loading the inbox")),
    );
    return () => {
      current = false;
    };
  }, [actingUser, attempt]);

  async function readOne(id: string): Promise<boolean> {
    setReading((s) => new Set(s).add(id));
    try {
      const result = await api.POST("/emails/{email_id}/interpret", { path: { email_id: id } });
      setReads((r) => ({ ...r, [id]: result }));
      return true;
    } catch (e) {
      setReadError(explain(e, "Reading the email"));
      return false;
    } finally {
      setReading((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
    }
  }

  async function sortAll() {
    if (!emails) return;
    setSortingAll(true);
    setReadError(null);
    const queue = emails.map((e) => e.email_id).filter((id) => !reads[id]);
    const worker = async () => {
      for (let id = queue.shift(); id; id = queue.shift()) await readOne(id);
    };
    await Promise.all(Array.from({ length: PARALLEL_READS }, worker));
    setSortingAll(false);
  }

  const q = search.trim().toLowerCase();
  const shown = (emails ?? []).filter((e) => {
    if (filter !== "all" && reads[e.email_id]?.category !== filter) return false;
    if (!q) return true;
    return [e.subject, e.from_name ?? "", e.from_address, e.snippet].some((s) =>
      s.toLowerCase().includes(q),
    );
  });
  const counts = CATEGORIES.map((c) => ({
    c,
    n: Object.values(reads).filter((r) => r.category === c).length,
  }));
  const readCount = Object.keys(reads).length;
  const activeId = selected ?? shown[0]?.email_id ?? null;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-start justify-between gap-6">
        <div className="flex max-w-3xl flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Messy inbox</h1>
          <p className="text-base text-muted-foreground">
            Emails as they arrive: mixed wording, mixed languages. The AI sorts each one by type and
            pulls out the key details, highlighting the exact words each detail came from. A person
            checks everything before it goes anywhere.
          </p>
        </div>
        <Button
          onClick={() => void sortAll()}
          disabled={!emails || sortingAll || readCount === (emails?.length ?? 0)}
          data-testid="sort-all"
        >
          {sortingAll ? (
            <Loader2 className="animate-spin" data-icon="inline-start" />
          ) : (
            <Sparkles data-icon="inline-start" />
          )}
          {sortingAll
            ? `Reading ${readCount} of ${emails?.length ?? 0}`
            : readCount > 0 && emails && readCount === emails.length
              ? "All emails sorted"
              : "Sort all with AI"}
        </Button>
      </header>

      {/* Always one chip-row tall, so nothing below moves when the first read lands. */}
      {readCount > 0 ? (
        <div
          className="flex min-h-8 flex-wrap items-center gap-2"
          role="radiogroup"
          aria-label="Show emails of type"
          data-testid="category-filter"
        >
          <FilterChip
            label="All"
            count={emails?.length ?? 0}
            active={filter === "all"}
            onClick={() => setFilter("all")}
          />
          {counts.map(({ c, n }) => (
            <FilterChip
              key={c}
              label={CATEGORY_TEXT[c]}
              count={n}
              help={CATEGORY_HELP[c]}
              active={filter === c}
              onClick={() => setFilter(c)}
            />
          ))}
        </div>
      ) : (
        <p
          className="flex min-h-8 items-center text-sm text-muted-foreground"
          data-testid="category-filter-hint"
        >
          Once the AI has read some emails, you can show one type at a time here.
        </p>
      )}

      {readError && (
        <p className="text-sm text-destructive" role="alert">
          {readError}
        </p>
      )}

      {error ? (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed p-6 text-sm">
          <p>{error}</p>
          <Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-[minmax(0,24rem)_minmax(0,1fr)] items-start gap-6">
          <div className="flex flex-col gap-2">
            <Input
              placeholder="Search by subject, sender or text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search emails"
            />
            <div className="h-[calc(100dvh-21.5rem)] min-h-96 overflow-y-auto rounded-xl border bg-card">
              {emails === null ? (
                <div className="flex flex-col gap-2 p-2">
                  {Array.from({ length: 8 }, (_, i) => (
                    <Skeleton key={i} className="h-16 w-full" />
                  ))}
                </div>
              ) : shown.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No email matches.</p>
              ) : (
                <ul className="divide-y" data-testid="email-list">
                  {shown.map((e) => (
                    <EmailRow
                      key={e.email_id}
                      email={e}
                      read={reads[e.email_id]}
                      busy={reading.has(e.email_id)}
                      active={e.email_id === activeId}
                      onClick={() => setSelected(e.email_id)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </div>
          {activeId ? (
            <EmailPane
              key={activeId}
              emailId={activeId}
              read={reads[activeId]}
              source={sources[activeId] ?? null}
              busy={reading.has(activeId)}
              onTraced={({ interpretation, source }) => {
                setReads((r) => ({ ...r, [activeId]: interpretation }));
                if (source) setSources((m) => ({ ...m, [activeId]: source }));
              }}
              onReadError={setReadError}
              onCreate={() => router.push(`/requests/new?email=${encodeURIComponent(activeId)}`)}
            />
          ) : (
            emails === null && <Skeleton className="h-[32rem] w-full" />
          )}
        </div>
      )}
    </div>
  );
}

function FilterChip({
  label,
  count,
  help,
  active,
  onClick,
}: {
  label: string;
  count: number;
  help?: string;
  active: boolean;
  onClick: () => void;
}) {
  const chip = (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-2 rounded-full border px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        active ? "border-foreground bg-foreground text-background" : "hover:bg-muted",
      )}
    >
      {label}
      <span className={cn("tabular-nums", active ? "text-background/70" : "text-muted-foreground")}>
        {count}
      </span>
    </button>
  );
  if (!help) return chip;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{chip}</TooltipTrigger>
      <TooltipContent className="max-w-64">{help}</TooltipContent>
    </Tooltip>
  );
}

function EmailRow({
  email: e,
  read,
  busy,
  active,
  onClick,
}: {
  email: EmailSummary;
  read?: Interpretation;
  busy: boolean;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        aria-current={active ? "true" : undefined}
        data-testid={`inbox-${e.email_id}`}
        className={cn(
          "flex w-full flex-col gap-1 px-3.5 py-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset",
          active ? "bg-muted" : "hover:bg-muted/50",
        )}
      >
        <span className="flex items-baseline justify-between gap-3">
          <span className="truncate text-sm font-medium">{e.from_name ?? e.from_address}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{formatSgt(e.received_at)}</span>
        </span>
        <span className="flex items-center gap-1.5 truncate text-sm">
          {e.has_attachments && <Paperclip className="size-3 shrink-0 text-muted-foreground" />}
          <span className="truncate">{e.subject}</span>
        </span>
        <span className="line-clamp-1 text-xs text-muted-foreground">{e.snippet}</span>
        <span className="flex h-5 items-center gap-1.5">
          {busy ? (
            <Skeleton className="h-4 w-24 rounded-full" />
          ) : read ? (
            <>
              <CategoryChip category={read.category} />
              {read.needs_review && (
                <Badge variant="secondary" className="bg-warning/15 text-warning-foreground">
                  Needs a person
                </Badge>
              )}
              {read.injection_suspected && <Badge variant="destructive">Suspicious</Badge>}
            </>
          ) : null}
        </span>
      </button>
    </li>
  );
}

/** How long a newly found quote stays in the stronger colour (D-023 #3). */
const FLASH_MS = 600;

function EmailPane({
  emailId,
  read,
  source,
  busy,
  onTraced,
  onReadError,
  onCreate,
}: {
  emailId: string;
  read?: Interpretation;
  source: TraceSource | null;
  busy: boolean;
  onTraced: (result: TraceResult) => void;
  onReadError: (message: string | null) => void;
  onCreate: () => void;
}) {
  const [email, setEmail] = useState<EmailDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  // The live trace: the view being filled in step by step, null when none is running.
  const [trace, setTrace] = useState<{ view: ReadView; source: TraceSource | null } | null>(null);
  const [tracing, setTracing] = useState(false);
  const [flashing, setFlashing] = useState<ReadonlySet<string>>(new Set());
  const [revealed, setRevealed] = useState<{ key: string; n: number } | null>(null);
  const reduced = usePrefersReducedMotion();
  const bodyRef = useRef<HTMLDivElement>(null);
  // Where keyboard focus goes when a read starts: the button that started it disappears.
  const readingRef = useRef<HTMLElement>(null);
  const controller = useRef<AbortController | null>(null);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    let current = true;
    api.GET("/emails/{email_id}", { path: { email_id: emailId } }).then(
      (e) => current && setEmail(e),
      (e: unknown) => current && setError(explain(e, "Opening the email")),
    );
    return () => {
      current = false;
    };
  }, [emailId]);

  // Leaving the email (or the page) stops its trace.
  useEffect(() => {
    const pending = timers.current;
    return () => {
      controller.current?.abort();
      pending.forEach((t) => window.clearTimeout(t));
    };
  }, []);

  // Bring each newly found quote into view once it is on screen.
  useEffect(() => {
    if (!revealed) return;
    bodyRef.current
      ?.querySelector(`[data-quote="${CSS.escape(revealed.key)}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }, [revealed, reduced]);

  function flash(key: string) {
    setFlashing((s) => new Set(s).add(key));
    setRevealed((r) => ({ key, n: (r?.n ?? 0) + 1 }));
    const t = window.setTimeout(() => {
      setFlashing((s) => {
        const next = new Set(s);
        next.delete(key);
        return next;
      });
    }, FLASH_MS);
    timers.current.push(t);
  }

  async function runTrace() {
    controller.current?.abort();
    const ctrl = new AbortController();
    controller.current = ctrl;
    const instant = prefersReducedMotion();
    onReadError(null);
    setFocusKey(null);
    setTracing(true);
    readingRef.current?.focus({ preventScroll: true });
    // Reduced motion: no step-by-step phase, the result shows all at once.
    // "Watch again" already knows where the answer comes from, so the status line says so at once.
    if (!instant) setTrace({ view: EMPTY_VIEW, source });
    try {
      const result = await interpretWithTrace(emailId, {
        signal: ctrl.signal,
        stepMs: instant ? 0 : undefined,
        onStep: instant
          ? undefined
          : (step) => {
              // A step from a read that was stopped (another email, Watch again) is dropped.
              if (ctrl.signal.aborted || controller.current !== ctrl) return;
              if (step.kind === "start") setTrace({ view: EMPTY_VIEW, source: step.source });
              else setTrace((t) => t && { ...t, view: applyStep(t.view, step) });
              if (step.kind === "field") flash(step.field.key);
              if (step.kind === "line") flash(`line-${step.index}`);
            },
      });
      if (!ctrl.signal.aborted) onTraced(result);
    } catch (e) {
      if (ctrl.signal.aborted) return;
      onReadError(explain(e, "Reading the email"));
    } finally {
      if (controller.current === ctrl) {
        controller.current = null;
        setTrace(null);
        setTracing(false);
      }
    }
  }

  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!email) return <Skeleton className="h-[32rem] w-full" />;

  const streaming = trace !== null;
  const view = trace?.view ?? (read ? viewOf(read) : null);
  const segments = highlight(email.body, view ? quotesOf(view) : []);

  const showQuote = (key: string) => {
    setFocusKey(key);
    bodyRef.current
      ?.querySelector(`[data-quote="${CSS.escape(key)}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  };

  return (
    <section
      className="grid grid-cols-[minmax(0,1fr)_minmax(0,22rem)] items-start gap-6 rounded-xl border bg-card p-6"
      aria-label={email.subject}
      data-testid="email-pane"
    >
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-semibold tracking-tight">{email.subject}</h2>
          <p className="text-sm text-muted-foreground">
            From{" "}
            {email.from_name ? `${email.from_name} <${email.from_address}>` : email.from_address}
            {email.to_address ? ` to ${email.to_address}` : ""}, {formatSgt(email.received_at)}
          </p>
          {(email.attachments ?? []).length > 0 && (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Paperclip className="size-3" />
              {(email.attachments ?? []).join(", ")} (attachments are not read in this demo)
            </p>
          )}
        </div>
        <div
          ref={bodyRef}
          className="rounded-lg bg-muted/30 p-4 text-sm leading-relaxed whitespace-pre-wrap"
          data-testid="email-body"
        >
          {segments.map((s, i) =>
            s.key ? (
              <mark
                key={i}
                data-quote={s.key}
                data-testid="quote-highlight"
                className={cn(
                  "rounded-sm px-0.5 text-foreground motion-safe:transition-colors motion-safe:duration-500",
                  flashing.has(s.key)
                    ? "bg-warning/75"
                    : focusKey === s.key
                      ? "bg-warning/60"
                      : "bg-warning/25",
                )}
              >
                {s.text}
              </mark>
            ) : (
              <span key={i}>{s.text}</span>
            ),
          )}
        </div>
      </div>

      <aside
        ref={readingRef}
        tabIndex={-1}
        className="flex flex-col gap-4 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        aria-label="What the AI read"
        aria-busy={streaming || undefined}
        data-testid="ai-reading"
        data-trace-state={streaming ? "streaming" : view ? "done" : undefined}
      >
        {!view ? (
          <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed p-4">
            <p className="text-sm text-muted-foreground">
              Let the AI sort this email and pull out the key details. It cannot act on anything it
              reads; it only suggests.
            </p>
            <Button
              onClick={() => void runTrace()}
              disabled={busy || tracing}
              data-testid="read-with-ai"
            >
              {busy || tracing ? (
                <Loader2 className="animate-spin" data-icon="inline-start" />
              ) : (
                <Sparkles data-icon="inline-start" />
              )}
              Read this email
            </Button>
          </div>
        ) : (
          <>
            <TraceBar
              source={trace ? trace.source : source}
              streaming={tracing}
              onReplay={() => void runTrace()}
            />
            <Reading
              view={view}
              source={trace ? trace.source : source}
              streaming={streaming}
              focusKey={focusKey}
              onFocusKey={showQuote}
              onCreate={onCreate}
            />
          </>
        )}
      </aside>
    </section>
  );
}
