"use client";

import { ArrowRight, Loader2, Mail, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { type DedupDecision, DuplicatePanel } from "@/components/dedup/duplicate-panel";
import { useDedupCheck } from "@/components/dedup/use-dedup-check";
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
import { api, isApiError, type Schema } from "@/lib/api/client";
import { DEMO_RESET_EVENT } from "@/lib/demo-events";
import { countryName } from "@/lib/format";
import {
  asFormSchema,
  COUNTRIES,
  type Country,
  type Domain,
  ENTITIES,
  ENTITY_NAMES,
  type Entity,
  type FieldValues,
  FORM_DOMAINS,
  type FormSpec,
  isFilled,
  missingRequired,
  syncRegistrations,
} from "@/lib/forms/schema";
import { cn } from "@/lib/utils";

import { EmailPicker } from "./email-picker";
import { FieldShell, isGroupField, SchemaInput } from "./fields";
import { RegistrationsInput } from "./registrations";

type FormDomain = (typeof FORM_DOMAINS)[number]["value"];
type RequestDetail = Schema<"RequestDetail">;

/** The country is chosen in the bar at the top, so the schema's own field is not repeated. */
const CONTEXT_FIELDS = new Set(["Country"]);
/** Long fields span both columns. */
const WIDE_TYPES = new Set(["array"]);

function readable(e: unknown, what: string): string {
  if (isApiError(e) && e.status === 501) {
    return `${what} isn't switched on in this build yet. Your form is kept; try again once the server is updated.`;
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
  const { persona } = usePersona();

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

  // Load the form definition for this domain x country.
  useEffect(() => {
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
  }, [domain, country, specAttempt]);

  const clearAll = () => {
    setValues({});
    setQuotes({});
    setPrefill(null);
    setReqId(null);
    setShowMissing(false);
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

  const dedup = useDedupCheck({
    enabled: isBusinessPartner && decision?.action !== "link_to_existing",
    domain: domain === "vendor" ? "vendor" : "customer",
    entity,
    fields: { ...values, Country: country },
    requestId: reqId,
  });

  const currentResult = dedup.status === "done" ? dedup.result : null;
  const candidateKey = (currentResult?.candidates ?? []).map((c) => c.CardCode).join(",");
  // A "not a duplicate" reason covers the candidates it was given for, not new ones.
  const activeDecision =
    decision &&
    (decision.action === "link_to_existing" || !currentResult || decidedFor === candidateKey)
      ? decision
      : null;
  const linked = activeDecision?.action === "link_to_existing";
  const blockingResult =
    dedup.status === "done" ? dedup.result : dedup.status === "checking" ? dedup.previous : null;
  const blocked = isBusinessPartner && !!blockingResult?.block_submit && !activeDecision;

  const missing = specReady ? missingRequired(values, spec) : [];

  function payloadFields(): FieldValues {
    if (!schema || !spec) return {};
    const out: FieldValues = {};
    for (const key of schema["x-order"]) {
      if (isFilled(values[key])) out[key] = values[key];
    }
    if ("Country" in schema.properties) out.Country = country;
    if (domain === "item") out.registrations = syncRegistrations(values, spec);
    return out;
  }

  /** Creates the draft the first time, then keeps it up to date. Returns its id. */
  async function ensureDraft(): Promise<string> {
    const fields = payloadFields();
    if (reqId) {
      await api.PATCH("/requests/{req_id}", {
        path: { req_id: reqId },
        body: { fields, country },
      });
      return reqId;
    }
    const created = await api.POST("/requests", {
      body: { domain, entity, country, fields, source_email_id: prefill?.emailId ?? null },
    });
    setReqId(created.req_id);
    return created.req_id;
  }

  async function decide(body: Schema<"DedupDecisionIn">): Promise<boolean> {
    setDeciding(true);
    setDecisionError(null);
    try {
      const id = await ensureDraft();
      await api.POST("/requests/{req_id}/dedup-decision", { path: { req_id: id }, body });
      setDecision(
        body.action === "link_to_existing"
          ? { action: "link_to_existing", card_code: body.card_code ?? "" }
          : { action: "not_duplicate", reason: body.reason ?? "" },
      );
      setDecidedFor(candidateKey);
      if (body.action === "link_to_existing") {
        toast.success(`Linked to ${body.card_code}`, {
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
      toast.success("Request submitted", { description: "Approvers have been notified." });
      router.push(`/requests/${id}`);
    } catch (e) {
      if (isApiError(e) && e.status === 422) setShowMissing(true);
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
      setValues(detail.fields);
      setQuotes(detail.prefill_quotes ?? {});
      setReqId(detail.req_id);
      setPrefill({ emailId: email.email_id, subject: email.subject });
      setShowMissing(true);
      return true;
    } catch (e) {
      toast.error("Could not pre-fill from that email", { description: readable(e, "Pre-filling") });
      return false;
    } finally {
      setPicking(null);
    }
  }

  const setField = (key: string, v: unknown) => setValues((prev) => ({ ...prev, [key]: v }));

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
                  setDecision(null);
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
            onValueChange={(v) => setEntityChoice(v as Entity)}
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
        )}
      >
        <form
          aria-label={`New ${domain} form`}
          className={cn("flex flex-col gap-6", !isBusinessPartner && "max-w-4xl")}
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
                .filter((key) => !CONTEXT_FIELDS.has(key) && schema.properties[key])
                .map((key) => {
                  const field = schema.properties[key]!;
                  const wide =
                    WIDE_TYPES.has(field.type ?? "") || (field.maxLength ?? 0) >= 200;
                  const isMissing =
                    showMissing &&
                    (missing.includes(key) ||
                      missing.some((m) => key === "registrations" && m.startsWith("registrations.")));
                  return (
                    <div key={key} className={cn(wide && "col-span-2")}>
                      <FieldShell
                        id={key}
                        label={field.title ?? key}
                        help={field.description}
                        required={spec.required.includes(key)}
                        missing={isMissing}
                        quote={quotes[key]}
                        sensitive={field["x-sensitive"]}
                        asGroup={isGroupField(field)}
                      >
                        {key === "registrations" ? (
                          <RegistrationsInput
                            field={field}
                            values={values}
                            spec={spec}
                            showMissing={showMissing}
                            onChange={(rows) => setField("registrations", rows)}
                          />
                        ) : (
                          <SchemaInput
                            id={key}
                            field={field}
                            value={values[key]}
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
                <p className="text-sm text-muted-foreground">
                  Nothing to submit: you are using the existing record.
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
                      : "Everything required is filled in."}
                </p>
              </div>
            )}
            {submitError && (
              <p className="text-sm text-destructive" role="alert" data-testid="submit-error">
                {submitError}
              </p>
            )}
          </div>
        </form>

        {isBusinessPartner && (
          <aside className="sticky top-24">
            <DuplicatePanel
              state={dedup}
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
