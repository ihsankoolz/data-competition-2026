"use client";

import {
  CloudOff,
  FilePlus2,
  Loader2,
  Paperclip,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UserRoundSearch,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

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
  CATEGORY_WITH_ARTICLE,
  type Category,
  highlight,
  type Interpretation,
  keyLabel,
  valueText,
} from "@/lib/emails";
import { formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";

type EmailSummary = Schema<"EmailSummary">;
type EmailDetail = Schema<"EmailDetail">;

const PARALLEL_READS = 6;

function explain(e: unknown, what: string): string {
  if (isApiError(e) && e.status === 501) return `${what} isn't switched on in this build yet.`;
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

      {readCount > 0 && (
        <div
          className="flex flex-wrap items-center gap-2"
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
            <div className="h-[calc(100dvh-20rem)] min-h-96 overflow-y-auto rounded-xl border">
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
              busy={reading.has(activeId)}
              onRead={() => void readOne(activeId)}
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

function CategoryChip({ category }: { category: Category }) {
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

function EmailPane({
  emailId,
  read,
  busy,
  onRead,
  onCreate,
}: {
  emailId: string;
  read?: Interpretation;
  busy: boolean;
  onRead: () => void;
  onCreate: () => void;
}) {
  const [email, setEmail] = useState<EmailDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

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

  if (error) return <p className="text-sm text-muted-foreground">{error}</p>;
  if (!email) return <Skeleton className="h-[32rem] w-full" />;

  const quotes = [
    ...(read?.fields ?? []).map((f) => ({ key: f.key, quote: f.source_quote })),
    ...(read?.lines ?? []).map((l, i) => ({ key: `line-${i}`, quote: l.source_quote })),
  ];
  const segments = highlight(email.body, quotes);

  const showQuote = (key: string) => {
    setFocusKey(key);
    bodyRef.current
      ?.querySelector(`[data-quote="${CSS.escape(key)}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };

  return (
    <section
      className="grid grid-cols-[minmax(0,1fr)_minmax(0,22rem)] items-start gap-6 rounded-xl border p-6"
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
                  "rounded-sm px-0.5 text-foreground transition-colors",
                  focusKey === s.key ? "bg-warning/60" : "bg-warning/25",
                )}
              >
                {s.text}
              </mark>
            ) : (
              <span key={i}>{s.text}</span>
            ),
          )}
        </div>
        {read?.bank_details_stripped && (
          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-3 shrink-0" />
            Bank details in this email were removed before the AI read it. They are never sent to
            the AI, and only Finance can see them.
          </p>
        )}
      </div>

      <aside className="flex flex-col gap-4" aria-label="What the AI read" data-testid="ai-reading">
        {!read ? (
          <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed p-4">
            <p className="text-sm text-muted-foreground">
              Let the AI sort this email and pull out the key details. It cannot act on anything it
              reads; it only suggests.
            </p>
            <Button onClick={onRead} disabled={busy} data-testid="read-with-ai">
              {busy ? (
                <Loader2 className="animate-spin" data-icon="inline-start" />
              ) : (
                <Sparkles data-icon="inline-start" />
              )}
              Read with AI
            </Button>
          </div>
        ) : (
          <Reading read={read} focusKey={focusKey} onFocusKey={showQuote} onCreate={onCreate} />
        )}
      </aside>
    </section>
  );
}

function Reading({
  read,
  focusKey,
  onFocusKey,
  onCreate,
}: {
  read: Interpretation;
  focusKey: string | null;
  onFocusKey: (key: string) => void;
  onCreate: () => void;
}) {
  const pct = Math.round(read.confidence * 100);
  const fields = read.fields ?? [];
  const lines = read.lines ?? [];
  const missing = read.missing_fields ?? [];
  const questions = read.questions_for_requester ?? [];

  return (
    <>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <CategoryChip category={read.category} />
          {read.method === "keyword_fallback" && (
            <Badge variant="outline" data-testid="ai-offline">
              <CloudOff data-icon="inline-start" />
              AI offline
            </Badge>
          )}
          {read.needs_review && (
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
          The AI is {pct}% sure this is {CATEGORY_WITH_ARTICLE[read.category]}.
          <span className="text-muted-foreground">
            {" "}
            {read.injection_suspected
              ? "The email seems to give the AI orders, so a person sorts it."
              : read.needs_review
                ? "That is below 60%, so a person sorts it."
                : CATEGORY_HELP[read.category]}
          </span>
        </p>
        {read.method === "keyword_fallback" && (
          <p className="text-xs text-muted-foreground">
            {read.ai_message ?? "AI offline: showing the keyword rules' best guess"}.
          </p>
        )}
      </div>

      {read.injection_suspected && (
        <div
          className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm"
          data-testid="injection-warning"
          role="alert"
        >
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
          <p>
            <span className="font-medium">Injection suspected.</span> This email seems to give
            instructions to the AI. They were ignored: an email can never change approvers, bank
            details or credit terms. A person should check it.
          </p>
        </div>
      )}

      {fields.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">Details found</h3>
          <ul className="flex flex-col gap-1" data-testid="extracted-fields">
            {fields.map((f) => (
              <li key={f.key}>
                <button
                  type="button"
                  onMouseEnter={() => onFocusKey(f.key)}
                  onFocus={() => onFocusKey(f.key)}
                  onClick={() => onFocusKey(f.key)}
                  className={cn(
                    "flex w-full flex-col gap-0.5 rounded-md px-2 py-1.5 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    focusKey === f.key ? "bg-warning/20" : "hover:bg-muted",
                  )}
                  data-testid={`extracted-${f.key}`}
                >
                  <span className="text-xs text-muted-foreground">{keyLabel(f.key)}</span>
                  <span className="text-sm font-medium break-words">{valueText(f.value)}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            Point at a detail to see the words it came from, highlighted in the email.
          </p>
        </div>
      )}

      {lines.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">Products and quantities</h3>
          <ul className="flex flex-col gap-1 text-sm" data-testid="order-lines">
            {lines.map((l, i) => (
              <li key={i}>
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

      {(missing.length > 0 || questions.length > 0) && (
        <div className="flex flex-col gap-2" data-testid="missing-fields">
          <h3 className="text-sm font-semibold">Missing from the email</h3>
          {questions.length > 0 ? (
            <ul className="flex list-disc flex-col gap-1 pl-5 text-sm">
              {questions.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm">{missing.map(keyLabel).join(", ")}</p>
          )}
          <p className="text-xs text-muted-foreground">
            The form asks the requestor for these before anything reaches an approver.
          </p>
        </div>
      )}

      {read.category === "mdm_request" && (
        <div className="flex flex-col gap-2 border-t pt-4">
          <Button onClick={onCreate} data-testid="create-request">
            <FilePlus2 data-icon="inline-start" />
            Create request from this email
          </Button>
          <p className="text-xs text-muted-foreground">
            Opens the request form filled in with these details, each one showing where it came
            from. Nothing is submitted until you check it.
          </p>
        </div>
      )}
    </>
  );
}
