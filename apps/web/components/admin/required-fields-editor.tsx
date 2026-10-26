"use client";

import { Lock } from "lucide-react";
import { useEffect, useState } from "react";

import { usePersona } from "@/components/shell/persona-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useActingUserId } from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { DEMO_RESET_EVENT } from "@/lib/demo-events";
import { formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";

type View = Schema<"RequiredFieldsView">;
type Row = Schema<"RequiredFieldRow">;
type Change = Schema<"RequiredFieldChange">;
type Domain = View["domain"];
type Country = View["country"];

const DOMAINS: { value: Domain; label: string; plural: string }[] = [
  { value: "customer", label: "Customer", plural: "customers" },
  { value: "vendor", label: "Vendor", plural: "vendors" },
  { value: "item", label: "Item", plural: "items" },
  { value: "cost_center", label: "Cost Center", plural: "cost centers" },
];
const COUNTRIES: { value: Country; label: string }[] = [
  { value: "SG", label: "Singapore" },
  { value: "MY", label: "Malaysia" },
  { value: "ID", label: "Indonesia" },
  { value: "VN", label: "Vietnam" },
  { value: "TH", label: "Thailand" },
];

const FIELD =
  "h-8 min-w-0 rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

function explain(e: unknown, fallback: string): string {
  return isApiError(e) ? e.message : fallback;
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="ml-2 rounded-md bg-primary/10 px-1.5 py-0.5 text-xs font-normal text-primary">
      {children}
    </span>
  );
}

/** A required / optional switch. Native checkbox underneath, so keyboards and readers just work. */
function RequiredSwitch({
  field,
  label,
  checked,
  disabled,
  onChange,
}: {
  field: string;
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={`${label} is required`}
      data-testid={`req-switch-${field}`}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60",
        checked ? "border-primary bg-primary" : "border-input bg-muted",
      )}
    >
      <span
        className={cn(
          "inline-block size-4 rounded-full bg-background shadow-xs transition-transform",
          checked ? "translate-x-4" : "translate-x-0.5",
        )}
      />
    </button>
  );
}

export function RequiredFieldsEditor() {
  const actingUser = useActingUserId();
  const { persona } = usePersona();
  const canEdit = !!persona?.roles.includes("mdm_analyst");

  const [attempt, setAttempt] = useState(0);
  const [domain, setDomain] = useState<Domain>("customer");
  const [country, setCountry] = useState<Country>("SG");
  const key = `${domain}/${country}`;

  const [loaded, setLoaded] = useState<{ key: string; view: View } | null>(null);
  const [changes, setChanges] = useState<Change[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Switches the person has flipped but not saved yet, for one record type and country.
  const [draft, setDraft] = useState<{ key: string; values: Record<string, boolean> } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  // "Reset demo" puts every field back to the standard rules: drop the view and any draft.
  useEffect(() => {
    const onReset = () => {
      setDraft(null);
      setSaved(null);
      setSaveError(null);
      setAttempt((n) => n + 1);
    };
    window.addEventListener(DEMO_RESET_EVENT, onReset);
    return () => window.removeEventListener(DEMO_RESET_EVENT, onReset);
  }, []);

  useEffect(() => {
    if (!actingUser) return;
    let current = true;
    Promise.all([
      api.GET("/admin/required-fields", { query: { domain, country } }),
      api.GET("/admin/required-field-changes"),
    ]).then(
      ([view, list]) => {
        if (!current) return;
        setLoaded({ key: `${domain}/${country}`, view });
        setChanges(list);
        setLoadError(null);
      },
      (e: unknown) =>
        current && setLoadError(explain(e, "The required-field settings could not be loaded.")),
    );
    return () => {
      current = false;
    };
  }, [actingUser, domain, country, attempt]);

  const view = loaded?.key === key ? loaded.view : null;
  const values = draft?.key === key ? draft.values : {};
  const nowRequired = (row: Row) => (row.locked ? true : (values[row.field] ?? row.required));
  const pending = (row: Row) =>
    !row.locked && row.field in values && values[row.field] !== row.required;
  const dirty = !!view && view.fields.some(pending);

  function flip(row: Row, next: boolean) {
    setDraft({ key, values: { ...values, [row.field]: next } });
    setSaved(null);
    setSaveError(null);
  }

  const domainWords = DOMAINS.find((d) => d.value === domain)?.plural ?? domain;
  const countryName = COUNTRIES.find((c) => c.value === country)?.label ?? country;

  async function save() {
    if (!view) return;
    const fields = view.fields
      .filter(pending)
      .map((r) => ({ field: r.field, required: values[r.field]! }));
    if (fields.length === 0) return;
    setSaving(true);
    setSaveError(null);
    setSaved(null);
    try {
      await api.PUT("/admin/required-fields", { body: { domain, country, fields } });
      setDraft(null);
      setSaved(`Saved. New requests for ${domainWords} in ${countryName} use these rules.`);
      setAttempt((n) => n + 1);
    } catch (e) {
      setSaveError(explain(e, "The change could not be saved."));
    } finally {
      setSaving(false);
    }
  }

  if (loadError) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {loadError}
      </p>
    );
  }

  return (
    <section
      aria-label="Required fields"
      data-testid="required-editor"
      className="flex max-w-5xl flex-col gap-5"
    >
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold tracking-tight">Required fields</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Choose a kind of record and a country, then switch a field between required and optional.
          No change to the software is needed. A few fields are locked because SAP, the approvers or
          the duplicate check rely on them.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Record type</span>
          <select
            className={FIELD}
            data-testid="req-domain"
            value={domain}
            onChange={(e) => setDomain(e.target.value as Domain)}
          >
            {DOMAINS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Country</span>
          <select
            className={FIELD}
            data-testid="req-country"
            value={country}
            onChange={(e) => setCountry(e.target.value as Country)}
          >
            {COUNTRIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!view ? (
        <Skeleton className="h-72 w-full rounded-xl" />
      ) : (
        <ul className="flex flex-col divide-y rounded-xl border bg-card" data-testid="req-rows">
          {view.fields.map((row) => {
            const on = nowRequired(row);
            return (
              <li
                key={row.field}
                data-testid={`req-row-${row.field}`}
                data-locked={row.locked}
                data-required={on}
                className={cn(
                  "flex items-center justify-between gap-4 px-4 py-2.5",
                  row.locked && "bg-muted/40",
                )}
              >
                <div className="flex min-w-0 flex-col">
                  <span className={cn("text-sm font-medium", row.locked && "text-muted-foreground")}>
                    {row.label}
                    {pending(row) ? (
                      <Badge>Unsaved change</Badge>
                    ) : row.changed ? (
                      <Badge>Changed from the standard</Badge>
                    ) : null}
                  </span>
                  {row.locked ? (
                    <span
                      className="mt-0.5 flex items-start gap-1.5 text-xs text-muted-foreground"
                      data-testid={`req-locked-${row.field}`}
                    >
                      <Lock className="mt-0.5 size-3 shrink-0" aria-hidden />
                      Always required. {row.locked_reason}
                    </span>
                  ) : row.help ? (
                    <span className="text-xs text-muted-foreground">{row.help}</span>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <span className="w-16 text-right text-xs text-muted-foreground">
                    {on ? "Required" : "Optional"}
                  </span>
                  <RequiredSwitch
                    field={row.field}
                    label={row.label}
                    checked={on}
                    disabled={!canEdit || row.locked || saving}
                    onChange={(next) => flip(row, next)}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          data-testid="req-save"
          disabled={!canEdit || saving || !dirty}
          onClick={() => void save()}
        >
          Save changes
        </Button>
        {dirty ? (
          <Button variant="ghost" onClick={() => setDraft(null)} disabled={saving}>
            Discard
          </Button>
        ) : null}
        {!canEdit ? (
          <p className="text-sm text-muted-foreground" data-testid="req-save-note">
            Only the MDM team can change which fields are required. Switch to Priya to edit.
          </p>
        ) : null}
      </div>
      {saveError ? (
        <p className="text-sm text-destructive" role="alert" data-testid="req-error">
          {saveError}
        </p>
      ) : null}
      {saved ? (
        <p className="text-sm text-muted-foreground" role="status" data-testid="req-saved">
          {saved}
        </p>
      ) : null}
      <p className="text-sm text-muted-foreground" data-testid="req-applies-note">
        {view?.note ?? "Applies to new requests only."}
      </p>

      <div className="flex flex-col gap-2" data-testid="req-changes">
        <h3 className="text-sm font-semibold">Recent changes to required fields</h3>
        {changes === null ? (
          <Skeleton className="h-10 w-full" />
        ) : changes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No field has been changed yet. Every change you save will be listed here.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {changes.map((c) => (
              <li key={c.id} data-testid="req-change" className="rounded-lg border bg-card p-3">
                <p className="text-sm font-medium">{c.summary}</p>
                <p className="text-xs text-muted-foreground">{formatSgt(c.at)}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
