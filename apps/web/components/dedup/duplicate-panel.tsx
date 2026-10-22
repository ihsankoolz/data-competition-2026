"use client";

import {
  Bot,
  BotOff,
  Check,
  CircleAlert,
  Equal,
  Link2,
  Loader2,
  Minus,
  ShieldCheck,
  TriangleAlert,
  Waypoints,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
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
import type { Schema } from "@/lib/api/client";
import { countryName } from "@/lib/format";
import type { FieldValues } from "@/lib/forms/schema";
import { cn } from "@/lib/utils";

import type { DedupResult, DedupState } from "./use-dedup-check";

type Candidate = Schema<"Candidate">;

export type DedupDecision =
  { action: "link_to_existing"; card_code: string } | { action: "not_duplicate"; reason: string };

export const MIN_REASON_LENGTH = 10;

/** Lowercase, accents and punctuation removed: "Bệnh viện Chợ Rẫy" -> "benhviencho ray". */
function simplify(s: string): string {
  return s
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/đ/gi, "d")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]/gu, "");
}

type Match = "same" | "same_unaccented" | "similar" | "different" | "empty";

function compare(a: unknown, b: unknown, similar = false): Match {
  const x = typeof a === "string" ? a.trim() : a == null ? "" : String(a);
  const y = typeof b === "string" ? b.trim() : b == null ? "" : String(b);
  if (!x || !y) return "empty";
  if (x.toLowerCase() === y.toLowerCase()) return "same";
  if (simplify(x) === simplify(y)) return "same_unaccented";
  return similar ? "similar" : "different";
}

const MATCH_TEXT: Record<Match, string> = {
  same: "Same",
  same_unaccented: "Same without accents",
  similar: "Very similar",
  different: "Different",
  empty: "",
};

type Row = { label: string; typed: string; existing: string; match: Match };

function rowsFor(c: Candidate, typed: FieldValues, entity: string, country: string): Row[] {
  const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));
  const nameSimilar = c.name_score >= 0.85;
  const taxMatch: Match = c.tax_id_match ? "same" : compare(typed.FederalTaxID, c.FederalTaxID);
  return [
    {
      label: "Legal name",
      typed: str(typed.CardName),
      existing: c.CardName,
      match: compare(typed.CardName, c.CardName, nameSimilar),
    },
    {
      label: "Other name",
      typed: str(typed.CardForeignName),
      existing: str(c.CardForeignName),
      match: compare(typed.CardForeignName, c.CardForeignName),
    },
    {
      label: "Tax ID",
      typed: str(typed.FederalTaxID),
      existing: str(c.FederalTaxID),
      match: taxMatch,
    },
    {
      label: "City",
      typed: str(typed.City),
      existing: str(c.city),
      match: compare(typed.City, c.city),
    },
    {
      label: "Entity",
      typed: entity,
      existing: str(c.entity),
      match: compare(entity, c.entity),
    },
    {
      label: "Country",
      typed: countryName(country),
      existing: countryName(c.country),
      match: compare(country, c.country),
    },
  ];
}

function MatchMark({ match }: { match: Match }) {
  if (match === "empty") return <Minus className="size-3.5 text-muted-foreground/50" aria-hidden />;
  const isMatch = match !== "different";
  return (
    <span
      className={cn(
        "inline-flex items-start gap-1 text-xs",
        isMatch ? "font-medium text-foreground" : "text-muted-foreground",
      )}
    >
      {isMatch ? <Equal className="mt-px size-3.5 shrink-0" aria-hidden /> : null}
      {MATCH_TEXT[match]}
    </span>
  );
}

function ComparisonTable({ rows, cardCode }: { rows: Row[]; cardCode: string }) {
  return (
    <table className="w-full table-fixed border-collapse text-sm" data-testid="comparison">
      <colgroup>
        <col className="w-24" />
        <col />
        <col />
        <col className="w-28" />
      </colgroup>
      <thead>
        <tr className="text-left text-xs text-muted-foreground">
          <th scope="col" className="pb-2 font-normal">
            <span className="sr-only">Field</span>
          </th>
          <th scope="col" className="pb-2 font-medium">
            Your request
          </th>
          <th scope="col" className="pb-2 font-medium">
            Existing record {cardCode}
          </th>
          <th scope="col" className="pb-2 font-normal">
            <span className="sr-only">Comparison</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const isMatch = r.match !== "different" && r.match !== "empty";
          return (
            <tr
              key={r.label}
              data-match={isMatch ? "true" : "false"}
              className={cn("border-t align-top", isMatch && "bg-warning/10")}
            >
              <th
                scope="row"
                className="py-2 pr-3 pl-2 text-left text-xs font-normal text-muted-foreground"
              >
                {r.label}
              </th>
              <td className="py-2 pr-3 break-words">{r.typed || <Empty />}</td>
              <td className="py-2 pr-3 break-words">{r.existing || <Empty />}</td>
              <td className="py-2 pr-2">
                <MatchMark match={r.match} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Empty() {
  return <span className="text-muted-foreground/60">Not given</span>;
}

function VerdictBanner({ result }: { result: DedupResult }) {
  if (result.verdict === "none") {
    return (
      <div className="flex items-start gap-3 text-sm" data-testid="verdict" data-verdict="none">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" />
        <p>{result.message || "No similar customer or vendor found. You can submit."}</p>
      </div>
    );
  }
  const likely = result.verdict === "likely";
  return (
    <div
      role="alert"
      data-testid="verdict"
      data-verdict={result.verdict}
      className={cn(
        "flex items-start gap-3 rounded-lg border p-3 text-sm",
        likely ? "border-destructive/40 bg-destructive/5" : "border-warning/50 bg-warning/10",
      )}
    >
      {likely ? (
        <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
      ) : (
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning-foreground" />
      )}
      <div className="flex flex-col gap-1">
        <p className="font-medium">
          {likely ? "Likely duplicate: submit is paused" : "Possible duplicate: please check"}
        </p>
        <p className="text-muted-foreground">{result.message}</p>
        <p className="text-muted-foreground">
          {likely
            ? "Link your request to the existing record, or explain why this is a different customer. You decide; the system never merges records on its own."
            : "You can still submit. Compare the records below and decide."}
        </p>
      </div>
    </div>
  );
}

function JudgeNote({
  judge,
  candidates,
}: {
  judge: DedupResult["judge"];
  candidates: Candidate[];
}) {
  if (!judge || judge.status === "not_needed" || judge.status === "disabled") return null;
  if (judge.status === "offline" || judge.status === "error") {
    return (
      <div className="flex items-start gap-2.5 text-sm" data-testid="judge">
        <Badge variant="outline" className="gap-1">
          <BotOff className="size-3" />
          AI offline
        </Badge>
        <p className="text-muted-foreground">
          The AI second opinion is unavailable. The checks above still ran and the choice is yours.
        </p>
      </div>
    );
  }
  const picked = candidates.find((c) => c.CardCode === judge.selected_card_code);
  return (
    <div className="flex flex-col gap-1.5 rounded-lg bg-muted/50 p-3 text-sm" data-testid="judge">
      <p className="flex items-center gap-2 font-medium">
        <Bot className="size-4 text-muted-foreground" />
        AI second opinion (advice only)
      </p>
      <p>
        {picked
          ? `It thinks your request is the same as ${picked.CardCode} (${picked.CardName}).`
          : "It thinks none of these records is the same as your request."}
      </p>
      {judge.reasons && judge.reasons.length > 0 && (
        <ul className="list-disc pl-5 text-muted-foreground">
          {judge.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">The AI never links or approves. You choose.</p>
    </div>
  );
}

function RelatedRecords({ related }: { related: Schema<"RelatedRecord">[] }) {
  if (related.length === 0) return null;
  const heading: Record<Schema<"RelatedRecord">["rule"], string> = {
    same_group_other_country: "Same hospital group in another country",
    other_country: "Same name in another country",
    customer_vendor: "The same company as a vendor",
  };
  return (
    <section className="flex flex-col gap-2" data-testid="related" aria-label="Related records">
      <h3 className="flex items-center gap-2 text-sm font-medium">
        <Waypoints className="size-4 text-muted-foreground" />
        Related, not duplicates
      </h3>
      <ul className="flex flex-col gap-2">
        {related.map((r) => (
          <li key={`${r.rule}-${r.CardCode}`} className="rounded-lg border px-3 py-2 text-sm">
            <p>
              <span className="font-medium">{heading[r.rule]}:</span> {r.CardName} ({r.CardCode},{" "}
              {countryName(r.country)})
            </p>
            <p className="text-xs text-muted-foreground">{r.explanation}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NotDuplicateDialog({
  domain,
  disabled,
  onConfirm,
}: {
  domain: "customer" | "vendor";
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
        <Button variant="outline" disabled={disabled} data-testid="not-duplicate">
          Not a duplicate — explain why
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Why is this a different {domain}?</DialogTitle>
          <DialogDescription>
            Your reason is saved with the request and shown to the approvers, so they can check it.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="not-duplicate-reason">Reason</Label>
          <Textarea
            id="not-duplicate-reason"
            rows={3}
            value={reason}
            placeholder="For example: a different legal entity with its own tax registration."
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
            onClick={async () => {
              setSaving(true);
              const ok = await onConfirm(reason.trim());
              setSaving(false);
              if (ok) setOpen(false);
            }}
          >
            {saving && <Loader2 className="animate-spin" data-icon="inline-start" />}
            Save reason
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export type DuplicatePanelProps = {
  state: DedupState;
  typed: FieldValues;
  entity: string;
  country: string;
  decision: DedupDecision | null;
  busy: boolean;
  error: string | null;
  onLink: (cardCode: string) => void;
  onNotDuplicate: (reason: string) => Promise<boolean>;
  domain: "customer" | "vendor";
};

export function DuplicatePanel(props: DuplicatePanelProps) {
  const { state, decision } = props;

  return (
    <section
      aria-label="Duplicate check"
      data-testid="dup-panel"
      className="flex flex-col gap-4 rounded-xl border bg-card p-5"
    >
      <header className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold">Duplicate check</h2>
        {state.status === "checking" && (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Checking
          </span>
        )}
      </header>
      {decision?.action === "link_to_existing" ? (
        <LinkedState cardCode={decision.card_code} />
      ) : (
        <PanelBody {...props} />
      )}
    </section>
  );
}

function LinkedState({ cardCode }: { cardCode: string }) {
  return (
    <div
      className="flex items-start gap-3 rounded-lg border border-success/40 bg-success/10 p-4"
      data-testid="linked"
      role="status"
    >
      <Link2 className="mt-0.5 size-5 shrink-0 text-success-foreground" />
      <div className="flex flex-col gap-1">
        <p className="font-medium">Linked to {cardCode}.</p>
        <p className="text-sm text-muted-foreground">
          No approval needed; the duplicate never reached an approver.
        </p>
      </div>
    </div>
  );
}

function PanelBody({
  state,
  typed,
  entity,
  country,
  decision,
  busy,
  error,
  onLink,
  onNotDuplicate,
  domain,
}: DuplicatePanelProps) {
  if (state.status === "idle") {
    return (
      <p className="text-sm text-muted-foreground">
        Type a legal name or tax ID. We check for an existing record as you type, before anyone has
        to approve it.
      </p>
    );
  }
  if (state.status === "unavailable") {
    return (
      <p
        className="flex items-start gap-2 text-sm text-muted-foreground"
        data-testid="dup-unavailable"
      >
        <CircleAlert className="mt-0.5 size-4 shrink-0" />
        {state.message}
      </p>
    );
  }
  const result = state.status === "done" ? state.result : state.previous;
  if (!result) {
    return (
      <div className="flex flex-col gap-2" aria-busy>
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  const candidates = result.candidates ?? [];
  return (
    <div className={cn("flex flex-col gap-5", state.status === "checking" && "opacity-60")}>
      <VerdictBanner result={result} />

      {candidates.map((c) => (
        <article
          key={c.CardCode}
          className="flex flex-col gap-3"
          data-testid="candidate"
          aria-label={`Existing record ${c.CardCode}`}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-medium">
              {c.CardName}{" "}
              <span className="font-normal text-muted-foreground">
                {c.CardCode}, {c.entity ?? "no entity"}, {countryName(c.country)}
              </span>
            </h3>
            <Badge variant={c.verdict === "likely" ? "destructive" : "secondary"}>
              {c.verdict === "likely" ? "Likely the same" : "Possibly the same"}
            </Badge>
          </div>
          <ComparisonTable rows={rowsFor(c, typed, entity, country)} cardCode={c.CardCode} />
          {c.reasons && c.reasons.length > 0 && (
            <div className="flex flex-col gap-1">
              <p className="text-xs text-muted-foreground">Why we think so</p>
              <ul className="flex flex-col gap-1 text-sm" data-testid="reasons">
                {c.reasons.map((r) => (
                  <li key={`${r.layer}-${r.text}`} className="flex items-start gap-2">
                    <Check className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                    {r.text}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <Button
              onClick={() => onLink(c.CardCode)}
              disabled={busy}
              data-testid={`link-${c.CardCode}`}
            >
              {busy ? (
                <Loader2 className="animate-spin" data-icon="inline-start" />
              ) : (
                <Link2 data-icon="inline-start" />
              )}
              Link to existing {c.CardCode}
            </Button>
          </div>
        </article>
      ))}

      {candidates.length > 0 && (
        <div className="flex flex-col gap-2 border-t pt-4">
          {decision?.action === "not_duplicate" ? (
            <div
              className="flex items-start gap-2 text-sm"
              data-testid="override-saved"
              role="status"
            >
              <Check className="mt-0.5 size-4 shrink-0 text-success" />
              <p>
                You marked this as a new customer: <q>{decision.reason}</q>. You can submit now.
              </p>
            </div>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                Sure it is a different customer or vendor?
              </p>
              <div>
                <NotDuplicateDialog domain={domain} disabled={busy} onConfirm={onNotDuplicate} />
              </div>
            </>
          )}
        </div>
      )}

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      <JudgeNote judge={result.judge} candidates={candidates} />
      <RelatedRecords related={result.related ?? []} />
    </div>
  );
}
