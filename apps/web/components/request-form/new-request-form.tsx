"use client";

import { ArrowRight, Loader2, Mail, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { type DedupDecision, DuplicatePanel } from "@/components/dedup/duplicate-panel";
import { ItemDuplicatePanel } from "@/components/dedup/item-duplicate-panel";
import { useDedupCheck } from "@/components/dedup/use-dedup-check";
import { useItemDedupCheck } from "@/components/dedup/use-item-dedup-check";
import { useClock } from "@/components/shell/clock-provider";
import { usePersona } from "@/components/shell/persona-provider";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isApiError, issuesOf, type Schema } from "@/lib/api/client";
import { announceWorkflowChange, DEMO_RESET_EVENT } from "@/lib/demo-events";
import { countryName, sgtDay } from "@/lib/format";
import {
  asFormSchema,
  COUNTRIES,
  type Country,
  type Domain,
  ENTITIES,
  ENTITY_NAMES,
  type Entity,
  expiredRegistrations,
  type FieldValues,
  FORM_DOMAINS,
  type FormSpec,
  isFilled,
  looksMasked,
  missingRequired,
  prefillableFields,
  syncRegistrations,
} from "@/lib/forms/schema";
import { toastAcrossNavigation } from "@/lib/toasts";
import { cn } from "@/lib/utils";

import { EmailPicker } from "./email-picker";
import { FieldShell, isGroupField, SchemaInput } from "./fields";
import { RegistrationsInput } from "./registrations";

type FormDomain = (typeof FORM_DOMAINS)[number]["value"];
type RequestDetail = Schema<"RequestDetail">;
type FieldIssue = Schema<"FieldIssue">;

/** "registrations.VN.reg_no" belongs to the registrations field; anything else to its own key. */
function issueKey(issue: FieldIssue): string {
  return issue.field.split(".")[0]!.split("[")[0]!;
}

/** The country is chosen in the bar at the top, so the schema's own field is not repeated. */
const CONTEXT_FIELDS = new Set(["Country"]);
const NO_CONTEXT_FIELDS = new Set<string>();
/** Long fields span both columns. */
const WIDE_TYPES = new Set(["array"]);

function readable(e: unknown, what: string): string {
  if (isApiError(e) && e.status === 501) {
    return `${what} isn't available right now. Your form is kept; try again in a moment.`;
  }
  if (isApiError(e)) return e.message;
  return `${what} did not work. Please try again.`;
}

function isFormDomain(d: Domain): d is FormDomain {
  return FORM_DOMAINS.some((f) => f.value === d);
}

type Prefill = { emailId: string; subject: string };

export function NewRequestForm() {
  const router = useRouter();
  const { persona, error: personaError } = usePersona();
  // Wait for the acting person so Marcus never sees a Singapore form flash first.
  const contextReady = persona !== null || personaError !== null;

  const [domain, setDomain] = useState<FormDomain>("customer");
  const [entityChoice, setEntityChoice] = useState<Entity | null>(null);
  const [countryChoice, setCountryChoice] = useState<Country | null>(null);
  const personaEntity = ENTITIES.find((e) => e === persona?.entity);
  const entity: Entity = entityChoice ?? personaEntity ?? "SPD";
  const personaCountry = COUNTRIES.find((c) => c === persona?.country);
  const country: Country = countryChoice ?? personaCountry ?? "SG";

  const [spec, setSpec] = useState<FormSpec | null>(null);
  const [specError, setSpecError] = useState<string | null>(null);
  const [specAttempt, setSpecAttempt] = useState(0);

  const [values, setValues] = useState<FieldValues>({});
  const [quotes, setQuotes] = useState<Record<string, string>>({});
  const [suggested, setSuggested] = useState<Record<string, string>>({});
  const [prefill, setPrefill] = useState<Prefill | null>(null);
  const [reqId, setReqId] = useState<string | null>(null);
  const [showMissing, setShowMissing] = useState(false);

  const [decision, setDecision] = useState<DedupDecision | null>(null);
  const [decidedFor, setDecidedFor] = useState<string>("");
  const [deciding, setDeciding] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const [picking, setPicking] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [issues, setIssues] = useState<FieldIssue[]>([]);

  // Load the form definition for this domain x country.
  useEffect(() => {
    if (!contextReady) return;
    let current = true;
    api.GET("/forms/{domain}", { path: { domain }, query: { country } }).then(
      (next) => {
        if (!current) return;
        setSpec(next);
        setSpecError(null);
      },
      (e: unknown) => current && setSpecError(readable(e, "Loading the form")),
    );
    return () => {
      current = false;
    };
  }, [domain, country, specAttempt, contextReady]);

  const clearAll = () => {
    setValues({});
    setQuotes({});
    setSuggested({});
    setPrefill(null);
    setReqId(null);
    setShowMissing(false);
    setDecision(null);
    setDecidedFor("");
    setDecisionError(null);
    setSubmitError(null);
    setIssues([]);
  };

  /**
   * A draft is created for one domain and entity, and the API cannot change
   * either later. When they change, drop the draft and its duplicate decision;
   * the next save creates a fresh draft.
   */
  const detachDraft = () => {
    setReqId(null);
    setDecision(null);
    setDecidedFor("");
    setDecisionError(null);
    setSubmitError(null);
  };

  // "Reset demo" in the header wipes the database, so a draft here is gone too.
  useEffect(() => {
    const onReset = () => {
      clearAll();
      setEntityChoice(null);
      setCountryChoice(null);
    };
    window.addEventListener(DEMO_RESET_EVENT, onReset);
    return () => window.removeEventListener(DEMO_RESET_EVENT, onReset);
  }, []);

  const specReady = spec !== null && spec.domain === domain && (spec.country ?? null) === country;
  const schema = specReady ? asFormSchema(spec) : null;
  const isBusinessPartner = domain === "customer" || domain === "vendor";
  const isItem = domain === "item"; // session 13: items get a duplicate check too
  const hasDupPanel = isBusinessPartner || isItem;
  // A vendor may be based anywhere (D-020 #2): its address country is a real field, defaulting
  // to the operating country. For customers the operating country is the address country.
  const vendorCountry = domain === "vendor";
  const contextFields = vendorCountry ? NO_CONTEXT_FIELDS : CONTEXT_FIELDS;
  const withCountry: FieldValues = vendorCountry
    ? { ...values, Country: isFilled(values.Country) ? values.Country : country }
    : { ...values, Country: country };

  const dedup = useDedupCheck({
    enabled: isBusinessPartner && decision?.action !== "link_to_existing",
    domain: domain === "vendor" ? "vendor" : "customer",
    entity,
    fields: withCountry,
    requestId: reqId,
  });

  const itemDedup = useItemDedupCheck({
    enabled: isItem && decision?.action !== "link_to_existing",
    fields: values,
    requestId: reqId,
  });

  const currentResult = dedup.status === "done" ? dedup.result : null;
  const currentItemResult = itemDedup.status === "done" ? itemDedup.result : null;
  const candidateKey = isItem
    ? (currentItemResult?.candidates ?? []).map((c) => c.ItemCode).join(",")
    : (currentResult?.candidates ?? []).map((c) => c.CardCode).join(",");
  const anyCurrent = isItem ? currentItemResult : currentResult;
  // A "not a duplicate" reason covers the candidates it was given for, not new ones.
  const activeDecision =
    decision &&
    (decision.action === "link_to_existing" || !anyCurrent || decidedFor === candidateKey)
      ? decision
      : null;
  const linked = activeDecision?.action === "link_to_existing";
  const blockingResult =
    dedup.status === "done" ? dedup.result : dedup.status === "checking" ? dedup.previous : null;
  const itemBlockingResult =
    itemDedup.status === "done"
      ? itemDedup.result
      : itemDedup.status === "checking"
        ? itemDedup.previous
        : null;
  const blocked =
    ((isBusinessPartner && !!blockingResult?.block_submit) ||
      (isItem && !!itemBlockingResult?.block_submit)) &&
    !activeDecision;

  // The country comes from the bar at the top, not from a form field, so count it as filled.
  const missing = specReady ? missingRequired(withCountry, spec) : [];
  // Registrations already expired on the demo clock (never the wall clock); the server checks too.
  const { clock } = useClock();
  const today = clock ? sgtDay(clock.now) : null;
  const expired = specReady && domain === "item" ? expiredRegistrations(values, spec, today) : {};
  const expiredMessages = Object.values(expired);
  // Once linked, the form is read-only: no "missing" highlights on fields nobody can fill.
  const flagMissing = showMissing && !linked;

  function payloadFields(): FieldValues {
    if (!schema || !spec) return {};
    const out: FieldValues = {};
    for (const key of schema["x-order"]) {
      // A masked value ("••••1234") is never sent back as if it were the real one.
      if (isFilled(values[key]) && !looksMasked(values[key])) out[key] = values[key];
    }
    if ("Country" in schema.properties) out.Country = withCountry.Country;
    if (domain === "item") out.registrations = syncRegistrations(values, spec);
    return out;
  }

  /** Creates the draft the first time, then keeps it up to date. Returns its id. */
  async function ensureDraft(): Promise<string> {
    const fields = payloadFields();
    if (reqId) {
      const updated = await api.PATCH("/requests/{req_id}", {
        path: { req_id: reqId },
        body: { fields, country },
      });
      setIssues(updated.issues ?? []);
      return reqId;
    }
    const created = await api.POST("/requests", {
      body: { domain, entity, country, fields, source_email_id: prefill?.emailId ?? null },
    });
    setReqId(created.req_id);
    setIssues(created.issues ?? []);
    return created.req_id;
  }

  async function decide(body: Schema<"DedupDecisionIn">): Promise<boolean> {
    setDeciding(true);
    setDecisionError(null);
    try {
      const id = await ensureDraft();
      await api.POST("/requests/{req_id}/dedup-decision", { path: { req_id: id }, body });
      const cardName = isItem
        ? (currentItemResult?.candidates ?? []).find((c) => c.ItemCode === body.card_code)
            ?.ItemName
        : (currentResult?.candidates ?? []).find((c) => c.CardCode === body.card_code)?.CardName;
      setDecision(
        body.action === "link_to_existing"
          ? { action: "link_to_existing", card_code: body.card_code ?? "", card_name: cardName }
          : { action: "not_duplicate", reason: body.reason ?? "" },
      );
      setDecidedFor(candidateKey);
      if (body.action === "link_to_existing") {
        const label = cardName ? `${cardName} (${body.card_code})` : body.card_code;
        toast.success(`Linked to ${label}`, {
          description: "No approval needed; nothing was sent to an approver.",
        });
      }
      return true;
    } catch (e) {
      setDecisionError(readable(e, "Saving your decision"));
      return false;
    } finally {
      setDeciding(false);
    }
  }

  async function submit() {
    setSubmitError(null);
    if (missing.length > 0) {
      setShowMissing(true);
      setSubmitError(
        `Fill in the ${missing.length === 1 ? "highlighted field" : `${missing.length} highlighted fields`} first.`,
      );
      return;
    }
    setSubmitting(true);
    try {
      const id = await ensureDraft();
      await api.POST("/requests/{req_id}/submit", { path: { req_id: id } });
      // The status page opens next; this toast is the one that stays through that change.
      toastAcrossNavigation(() =>
        toast.success("Request submitted", { description: "Approvers have been notified." }),
      );
      announceWorkflowChange();
      router.push(`/requests/${id}`);
    } catch (e) {
      if (isApiError(e) && e.status === 422) {
        setShowMissing(true);
        // Submit's 422 is {detail, issues}: the detail is the summary, issues go next to fields.
        setIssues(issuesOf(e));
      }
      setSubmitError(readable(e, "Submitting"));
    } finally {
      setSubmitting(false);
    }
  }

  async function pickEmail(email: Schema<"EmailSummary">): Promise<boolean> {
    setPicking(email.email_id);
    try {
      const detail: RequestDetail = await api.POST("/requests/from-email/{email_id}", {
        path: { email_id: email.email_id },
      });
      clearAll();
      if (isFormDomain(detail.domain)) setDomain(detail.domain);
      setEntityChoice(detail.entity);
      setCountryChoice(detail.country);
      // Never bank details or credit terms from the server, and nothing masked.
      setValues(prefillableFields(detail.fields, spec?.domain === detail.domain ? schema : null));
      setQuotes(detail.prefill_quotes ?? {});
      setSuggested(detail.prefill_suggested ?? {});
      setIssues(detail.issues ?? []);
      setReqId(detail.req_id);
      setPrefill({ emailId: email.email_id, subject: email.subject });
      setShowMissing(true);
      return true;
    } catch (e) {
      toast.error("Could not pre-fill from that email", {
        description: readable(e, "Pre-filling"),
      });
      return false;
    } finally {
      setPicking(null);
    }
  }

  const setField = (key: string, v: unknown) => {
    setValues((prev) => ({ ...prev, [key]: v }));
    // An edited field's server problem is out of date until the next check.
    setIssues((prev) => prev.filter((i) => issueKey(i) !== key));
  };

  // A "missing" issue only shows once the person has tried to submit (like the red outline).
  const shownIssues = linked
    ? []
    : issues.filter(
        (i) =>
          (i.kind !== "missing" || showMissing) &&
          // The live expiry message under the row already says this; don't say it twice.
          !(
            i.kind === "expired" && (expired as Record<string, string>)[i.field.split(".")[1] ?? ""]
          ),
      );
  const issuesFor = (key: string) =>
    shownIssues.filter((i) => issueKey(i) === key).map((i) => i.message);
  const placed = new Set(
    schema ? schema["x-order"].filter((k) => !contextFields.has(k) && schema.properties[k]) : [],
  );
  const unplacedIssues = shownIssues.filter((i) => !placed.has(issueKey(i)));

  return (
    <div className="flex flex-col gap-8">
      <header className="flex items-start justify-between gap-6">
        <div className="flex max-w-2xl flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">New request</h1>
          <p className="text-base text-muted-foreground">
            Ask for a new customer, vendor or item. The form asks only for what your country needs
            and warns you before you create a duplicate.
          </p>
        </div>
        <EmailPicker onPick={pickEmail} picking={picking} />
        <Suspense>
          <EmailHandoff ready={contextReady} onPick={pickEmail} />
        </Suspense>
      </header>

      <section
        aria-label="What you are requesting"
        className="flex flex-wrap items-end gap-6 border-b pb-6"
      >
        <div className="flex flex-col gap-1.5">
          <span id="domain-label" className="text-sm font-medium">
            Request a new
          </span>
          <div
            role="radiogroup"
            aria-labelledby="domain-label"
            className="inline-flex h-9 rounded-lg border bg-muted/40 p-0.5"
          >
            {FORM_DOMAINS.map((d) => (
              <button
                key={d.value}
                type="button"
                role="radio"
                aria-checked={domain === d.value}
                disabled={linked}
                onClick={() => {
                  if (d.value === domain) return;
                  setDomain(d.value);
                  detachDraft();
                  setShowMissing(false);
                }}
                className={cn(
                  "rounded-md px-4 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  domain === d.value
                    ? "bg-background font-medium shadow-xs"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex w-56 flex-col gap-1.5">
          <Label htmlFor="ctx-entity">For entity</Label>
          <Select
            value={entity}
            onValueChange={(v) => {
              if (v === entity) return;
              setEntityChoice(v as Entity);
              detachDraft();
            }}
            disabled={linked}
          >
            <SelectTrigger id="ctx-entity" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ENTITIES.map((e) => (
                <SelectItem key={e} value={e}>
                  {ENTITY_NAMES[e]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex w-44 flex-col gap-1.5">
          <Label htmlFor="ctx-country">In country</Label>
          <Select
            value={country}
            onValueChange={(v) => setCountryChoice(v as Country)}
            disabled={linked}
          >
            <SelectTrigger id="ctx-country" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {COUNTRIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {countryName(c)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {(prefill || reqId || Object.keys(values).length > 0) && !linked && (
          <Button variant="ghost" size="sm" className="ml-auto" onClick={clearAll}>
            <X data-icon="inline-start" />
            Start over
          </Button>
        )}
      </section>

      {prefill && (
        <div
          className="flex items-start gap-3 rounded-lg border bg-muted/40 p-3 text-sm"
          data-testid="prefill-note"
        >
          <Mail className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <p>
            Pre-filled from the email <q className="font-medium">{prefill.subject}</q>. Under each
            filled field you can see the words it came from. Check them, and fill in anything
            outlined in red.
          </p>
        </div>
      )}

      <div
        className={cn(
          "grid items-start gap-8",
          isBusinessPartner && "grid-cols-[minmax(0,1fr)_minmax(0,32rem)]",
          isItem && "grid-cols-[minmax(0,1fr)_minmax(0,24rem)]",
        )}
      >
        <form
          aria-label={`New ${domain} form`}
          className={cn("flex flex-col gap-6", !hasDupPanel && "max-w-4xl")}
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {specError ? (
            <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed p-6 text-sm">
              <p>{specError}</p>
              <Button variant="outline" size="sm" onClick={() => setSpecAttempt((n) => n + 1)}>
                Try again
              </Button>
            </div>
          ) : !schema || !spec ? (
            <FormSkeleton />
          ) : (
            <fieldset disabled={linked} className="grid grid-cols-2 gap-x-6 gap-y-5">
              <legend className="sr-only">{schema.title}</legend>
              {schema["x-order"]
                .filter((key) => !contextFields.has(key) && schema.properties[key])
                .map((key) => {
                  const field = schema.properties[key]!;
                  const wide = WIDE_TYPES.has(field.type ?? "") || (field.maxLength ?? 0) >= 200;
                  // Registration rows highlight themselves, one per country.
                  const isMissing = flagMissing && missing.includes(key);
                  return (
                    <div key={key} className={cn(wide && "col-span-2")}>
                      <FieldShell
                        id={key}
                        label={field.title ?? key}
                        help={field.description}
                        required={spec.required.includes(key)}
                        missing={isMissing}
                        issues={issuesFor(key)}
                        quote={quotes[key]}
                        suggestion={suggested[key]}
                        sensitive={field["x-sensitive"]}
                        asGroup={isGroupField(field)}
                      >
                        {key === "registrations" ? (
                          <RegistrationsInput
                            field={field}
                            values={values}
                            spec={spec}
                            showMissing={flagMissing}
                            expired={linked ? {} : expired}
                            onChange={(rows) => setField("registrations", rows)}
                          />
                        ) : (
                          <SchemaInput
                            id={key}
                            field={field}
                            value={key === "Country" ? withCountry.Country : values[key]}
                            invalid={isMissing}
                            onChange={(v) => setField(key, v)}
                          />
                        )}
                      </FieldShell>
                    </div>
                  );
                })}
            </fieldset>
          )}

          <div className="flex flex-col gap-3 border-t pt-5">
            {linked ? (
              <div className="flex items-center gap-3">
                <Button asChild>
                  <Link href={`/requests/${reqId}`}>
                    See the request
                    <ArrowRight data-icon="inline-end" />
                  </Link>
                </Button>
                <p className="text-sm text-muted-foreground" data-testid="linked-note">
                  Linked to{" "}
                  {activeDecision?.action === "link_to_existing" && activeDecision.card_name
                    ? `${activeDecision.card_name} (${activeDecision.card_code})`
                    : activeDecision?.action === "link_to_existing"
                      ? activeDecision.card_code
                      : "the existing record"}
                  . Nothing to submit: you are using the existing record.
                </p>
              </div>
            ) : (
              <div className="flex items-center gap-4">
                <Button
                  type="submit"
                  disabled={!specReady || blocked || submitting || deciding}
                  data-testid="submit"
                >
                  {submitting && <Loader2 className="animate-spin" data-icon="inline-start" />}
                  Submit for approval
                </Button>
                <p className="text-sm text-muted-foreground" data-testid="submit-hint">
                  {blocked
                    ? "Paused: decide on the likely duplicate first."
                    : missing.length > 0
                      ? `${missing.length} required ${missing.length === 1 ? "field is" : "fields are"} still empty.`
                      : expiredMessages.length > 0
                        ? `${expiredMessages.length === 1 ? "A registration has" : `${expiredMessages.length} registrations have`} expired: renew or remove ${expiredMessages.length === 1 ? "it" : "them"} first.`
                        : "Everything required is filled in."}
                </p>
              </div>
            )}
            {submitError && (
              <p className="text-sm text-destructive" role="alert" data-testid="submit-error">
                {submitError}
              </p>
            )}
            {unplacedIssues.length > 0 && (
              <ul
                className="flex flex-col gap-1 text-sm text-destructive"
                data-testid="other-issues"
              >
                {unplacedIssues.map((i) => (
                  <li key={`${i.field}-${i.message}`}>
                    <span className="font-medium">{i.label}:</span> {i.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </form>

        {isItem && (
          <aside className="sticky top-24">
            <ItemDuplicatePanel
              state={itemDedup}
              typedName={typeof values.ItemName === "string" ? values.ItemName : ""}
              decision={activeDecision}
              busy={deciding}
              error={decisionError}
              onLink={(card_code) => void decide({ action: "link_to_existing", card_code })}
              onNotDuplicate={(reason) => decide({ action: "not_duplicate", reason })}
            />
          </aside>
        )}

        {isBusinessPartner && (
          <aside className="sticky top-24">
            <DuplicatePanel
              state={dedup}
              domain={domain === "vendor" ? "vendor" : "customer"}
              typed={values}
              entity={entity}
              country={country}
              decision={activeDecision}
              busy={deciding}
              error={decisionError}
              onLink={(card_code) => void decide({ action: "link_to_existing", card_code })}
              onNotDuplicate={(reason) => decide({ action: "not_duplicate", reason })}
            />
          </aside>
        )}
      </div>
    </div>
  );
}

/**
 * `/requests/new?email=DEMO-01` (from the messy inbox) pre-fills the form from
 * that email once, through the same path as "Create from email".
 */
function EmailHandoff({
  ready,
  onPick,
}: {
  ready: boolean;
  onPick: (email: Schema<"EmailSummary">) => Promise<boolean>;
}) {
  const router = useRouter();
  const emailId = useSearchParams().get("email");
  const handled = useRef<string | null>(null);

  useEffect(() => {
    if (!ready || !emailId || handled.current === emailId) return;
    handled.current = emailId;
    // Drop ?email= at once, so a reload does not create a second draft from the same email.
    router.replace("/requests/new", { scroll: false });
    api.GET("/emails/{email_id}", { path: { email_id: emailId } }).then(
      (email) => void onPick(email),
      (e: unknown) =>
        toast.error("Could not open that email", { description: readable(e, "Opening the email") }),
    );
  }, [ready, emailId, onPick, router]);

  return null;
}

function FormSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-5" aria-busy aria-label="Loading the form">
      {Array.from({ length: 10 }, (_, i) => (
        <div key={i} className="flex flex-col gap-2">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-9 w-full" />
        </div>
      ))}
    </div>
  );
}
