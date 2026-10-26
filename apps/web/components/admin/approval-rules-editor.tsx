"use client";

import { Lock, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { usePersona } from "@/components/shell/persona-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useActingUserId } from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";

type Rules = Schema<"RoutingRules">;
type Rule = Schema<"RoutingRule">;
type Step = Schema<"RuleStepIn">;
type Preview = Schema<"RulePreview">;
type Change = Schema<"ConfigChange">;
type Domain = Schema<"RoutingRule">["domain"];
type Entity = Schema<"RoutingRule">["entity"];
type Country = Schema<"RoutingRule">["country"];

const DOMAINS: { value: Domain; label: string }[] = [
  { value: "customer", label: "Customer" },
  { value: "vendor", label: "Vendor" },
  { value: "item", label: "Item" },
  { value: "cost_center", label: "Cost Center" },
];
const ENTITIES: Entity[] = ["SPD", "QTS", "QTG"];
const COUNTRIES: { value: Country; label: string }[] = [
  { value: "SG", label: "Singapore" },
  { value: "MY", label: "Malaysia" },
  { value: "ID", label: "Indonesia" },
  { value: "VN", label: "Vietnam" },
  { value: "TH", label: "Thailand" },
];
const HAS_COUNTRY: Domain[] = ["customer", "vendor"];
const ALL_COUNTRIES = "*";

const FIELD =
  "h-8 min-w-0 rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

function sameSteps(a: Step[], b: Step[]): boolean {
  return (
    a.length === b.length && a.every((s, i) => s.role === b[i].role && s.user_id === b[i].user_id)
  );
}

function describe(domain: Domain, entity: Entity, country: Country): string {
  const type = DOMAINS.find((d) => d.value === domain)?.label.toLowerCase() ?? domain;
  const place =
    country === ALL_COUNTRIES
      ? "all countries"
      : (COUNTRIES.find((c) => c.value === country)?.label ?? country);
  return `${entity} ${type} requests (${place})`;
}

function explain(e: unknown, fallback: string): string {
  return isApiError(e) ? e.message : fallback;
}

export function ApprovalRulesEditor() {
  const actingUser = useActingUserId();
  const { persona } = usePersona();
  const canEdit = !!persona?.roles.includes("mdm_analyst");

  const [attempt, setAttempt] = useState(0);
  const [rules, setRules] = useState<Rules | null>(null);
  const [changes, setChanges] = useState<Change[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // The sample request the rule is being edited for. Marcus's world is the default.
  const [domain, setDomain] = useState<Domain>("customer");
  const [entity, setEntity] = useState<Entity>("QTG");
  const [country, setCountry] = useState<Country>("VN");
  const key = `${domain}/${entity}/${country}`;

  // An unsaved draft belongs to one key; changing the key starts again from the saved rule.
  const [draft, setDraft] = useState<{ key: string; steps: Step[] } | null>(null);
  const [adding, setAdding] = useState<{ role: Step["role"]; user_id: string }>({
    role: "quality_regulatory",
    user_id: "",
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (!actingUser) return;
    let current = true;
    Promise.all([api.GET("/admin/routing-rules"), api.GET("/admin/config-changes")]).then(
      ([r, c]) => {
        if (!current) return;
        setRules(r);
        setChanges(c);
        setLoadError(null);
      },
      (e: unknown) =>
        current && setLoadError(explain(e, "The approval rules could not be loaded.")),
    );
    return () => {
      current = false;
    };
  }, [actingUser, attempt]);

  const rule: Rule | undefined = rules?.rules.find(
    (r) => r.domain === domain && r.entity === entity && r.country === country,
  );
  const savedSteps: Step[] = (rule?.steps ?? []).map((s) => ({ role: s.role, user_id: s.user_id }));
  const steps = draft?.key === key ? draft.steps : savedSteps;
  const dirty = !!rule && !sameSteps(steps, savedSteps);

  function edit(next: Step[]) {
    setDraft({ key, steps: next });
    setSaved(null);
    setSaveError(null);
  }

  // "Who would approve this?" follows the draft, computed by the server's own routing code.
  const sig = JSON.stringify([key, steps]);
  const [preview, setPreview] = useState<{ sig: string; result?: Preview; error?: string } | null>(
    null,
  );
  useEffect(() => {
    if (!actingUser || !rules || steps.length === 0) return;
    let current = true;
    api.POST("/admin/routing-rules/preview", { body: { domain, entity, country, steps } }).then(
      (result) => current && setPreview({ sig, result }),
      (e: unknown) =>
        current && setPreview({ sig, error: explain(e, "The preview could not be loaded.") }),
    );
    return () => {
      current = false;
    };
    // `sig` holds the key and steps; the rest only matter through it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actingUser, rules, sig]);
  const shown = preview?.sig === sig ? preview : null;

  function chooseDomain(next: Domain) {
    setDomain(next);
    setCountry(
      HAS_COUNTRY.includes(next) ? (country === ALL_COUNTRIES ? "SG" : country) : ALL_COUNTRIES,
    );
  }

  const peopleFor = (role: Step["role"]) => rules?.roles.find((r) => r.role === role)?.people ?? [];
  const roleLabel = (role: string) => rules?.roles.find((r) => r.role === role)?.label ?? role;
  const adder = peopleFor(adding.role);
  const addUser = adder.some((p) => p.user_id === adding.user_id)
    ? adding.user_id
    : (adder[0]?.user_id ?? "");
  const nameOf = (userId: string) =>
    rules?.rules.flatMap((r) => r.steps).find((s) => s.user_id === userId)?.name ??
    rules?.roles.flatMap((r) => r.people).find((p) => p.user_id === userId)?.name ??
    userId;

  async function save() {
    setSaving(true);
    setSaveError(null);
    setSaved(null);
    try {
      await api.PUT("/admin/routing-rules", { body: { domain, entity, country, steps } });
      setDraft(null);
      setSaved(`Saved. New ${describe(domain, entity, country)} follow this route.`);
      setAttempt((n) => n + 1);
    } catch (e) {
      setSaveError(explain(e, "The rule could not be saved."));
    } finally {
      setSaving(false);
    }
  }

  async function resetToStandard() {
    setSaving(true);
    setSaveError(null);
    setSaved(null);
    try {
      await api.DELETE("/admin/routing-rules", { query: { domain, entity, country } });
      setDraft(null);
      setSaved(`Back to the standard route for ${describe(domain, entity, country)}.`);
      setAttempt((n) => n + 1);
    } catch (e) {
      setSaveError(explain(e, "The rule could not be reset."));
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
  if (!rules || !rule) {
    return <Skeleton className="h-96 w-full max-w-5xl rounded-xl" />;
  }

  const publish = shown?.result?.tasks.find((t) => t.stage > 1);

  return (
    <div className="flex flex-col gap-10">
      <section
        aria-label="Approval rules"
        data-testid="rules-editor"
        className="flex max-w-5xl flex-col gap-5"
      >
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-semibold tracking-tight">Approval rules</h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Choose a kind of request, then change who reviews it before MDM publishes it. A request
            keeps the route it had when it was submitted.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Record type</span>
            <select
              className={FIELD}
              data-testid="rule-domain"
              value={domain}
              onChange={(e) => chooseDomain(e.target.value as Domain)}
            >
              {DOMAINS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Entity</span>
            <select
              className={FIELD}
              data-testid="rule-entity"
              value={entity}
              onChange={(e) => setEntity(e.target.value as Entity)}
            >
              {ENTITIES.map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Country</span>
            <select
              className={FIELD}
              data-testid="rule-country"
              value={country}
              disabled={!HAS_COUNTRY.includes(domain)}
              onChange={(e) => setCountry(e.target.value as Country)}
            >
              {HAS_COUNTRY.includes(domain) ? (
                COUNTRIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))
              ) : (
                <option value={ALL_COUNTRIES}>All countries</option>
              )}
            </select>
          </label>
          <span
            className={cn(
              "rounded-md px-2 py-1 text-xs font-medium",
              rule.is_override ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
            )}
            data-testid="rule-source"
            data-override={rule.is_override}
          >
            {rule.is_override
              ? `Custom route, saved by ${rule.changed_by ?? "MDM"}${rule.changed_at ? ` on ${formatSgt(rule.changed_at)}` : ""}`
              : "Standard route"}
          </span>
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="flex flex-col gap-3">
            <h3 className="text-sm font-semibold">Who reviews first (all at the same time)</h3>
            {steps.length === 0 ? (
              <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                No approvers yet. Add at least one before saving.
              </p>
            ) : null}
            <ol className="flex flex-col gap-2" data-testid="rule-steps">
              {steps.map((s, i) => (
                <li
                  key={`${s.role}-${s.user_id}-${i}`}
                  data-testid="rule-step"
                  data-role={s.role}
                  data-user={s.user_id}
                  className="flex items-center justify-between gap-3 rounded-lg border bg-card px-3 py-2"
                >
                  <span className="flex flex-col text-sm">
                    <span className="font-medium">{nameOf(s.user_id)}</span>
                    <span className="text-muted-foreground">{roleLabel(s.role)}</span>
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!canEdit}
                    aria-label={`Remove ${nameOf(s.user_id)}`}
                    data-testid="remove-step"
                    onClick={() => edit(steps.filter((_, j) => j !== i))}
                  >
                    <Trash2 data-icon="inline-start" />
                    Remove
                  </Button>
                </li>
              ))}
              <li
                className="flex items-center gap-3 rounded-lg border border-dashed px-3 py-2 text-sm text-muted-foreground"
                data-testid="publish-step"
              >
                <Lock className="size-4 shrink-0" aria-hidden />
                <span>
                  <span className="font-medium text-foreground">
                    MDM publish{publish ? `: ${publish.name}` : ""}
                  </span>{" "}
                  (fixed, not editable)
                </span>
              </li>
            </ol>

            <div className="flex flex-wrap items-end gap-3 rounded-lg bg-muted/40 p-3">
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">Role</span>
                <select
                  className={FIELD}
                  data-testid="add-step-role"
                  value={adding.role}
                  disabled={!canEdit}
                  onChange={(e) => setAdding({ role: e.target.value as Step["role"], user_id: "" })}
                >
                  {rules.roles.map((r) => (
                    <option key={r.role} value={r.role}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">Person</span>
                <select
                  className={FIELD}
                  data-testid="add-step-person"
                  value={addUser}
                  disabled={!canEdit}
                  onChange={(e) => setAdding({ ...adding, user_id: e.target.value })}
                >
                  {adder.map((p) => (
                    <option key={p.user_id} value={p.user_id}>
                      {p.name} ({p.title})
                    </option>
                  ))}
                </select>
              </label>
              <Button
                variant="outline"
                data-testid="add-step"
                disabled={!canEdit || !addUser}
                onClick={() => edit([...steps, { role: adding.role, user_id: addUser }])}
              >
                <Plus data-icon="inline-start" />
                Add step
              </Button>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button
                data-testid="rule-save"
                disabled={!canEdit || saving || !dirty}
                onClick={() => void save()}
              >
                Save rule
              </Button>
              {canEdit && rule.is_override ? (
                <Button
                  variant="outline"
                  data-testid="rule-reset"
                  disabled={saving}
                  onClick={() => void resetToStandard()}
                >
                  Use the standard route
                </Button>
              ) : null}
              {!canEdit ? (
                <p className="text-sm text-muted-foreground" data-testid="rule-save-note">
                  Only the MDM team can change approval rules. Switch to Priya to edit.
                </p>
              ) : null}
            </div>
            {saveError ? (
              <p className="text-sm text-destructive" role="alert" data-testid="rule-error">
                {saveError}
              </p>
            ) : null}
            {saved ? (
              <p className="text-sm text-muted-foreground" role="status" data-testid="rule-saved">
                {saved}
              </p>
            ) : null}
            <p className="text-sm text-muted-foreground" data-testid="rule-applies-note">
              Changes apply to new requests only. Requests already in approval keep their approvers.
            </p>
          </div>

          <aside
            aria-label="Who would approve this?"
            data-testid="rule-preview"
            className="flex flex-col gap-3 self-start rounded-xl border bg-card p-4"
          >
            <div className="flex flex-col gap-1">
              <h3 className="text-sm font-semibold">Who would approve this?</h3>
              <p className="text-sm text-muted-foreground">
                A sample {describe(domain, entity, country)}
                {dirty ? ", with your unsaved changes" : ""}.
              </p>
            </div>
            {steps.length === 0 ? (
              <p className="text-sm text-muted-foreground">Add an approver to see the route.</p>
            ) : shown?.error ? (
              <p className="text-sm text-destructive" role="alert">
                {shown.error}
              </p>
            ) : shown?.result ? (
              <ol className="flex flex-col gap-2">
                {shown.result.tasks.map((t, i) => (
                  <li
                    key={`${t.stage}-${t.role}-${t.user_id}-${i}`}
                    data-testid="preview-task"
                    data-stage={t.stage}
                    data-user={t.user_id}
                    className="flex items-baseline justify-between gap-3 text-sm"
                  >
                    <span>
                      <span className="text-muted-foreground">Stage {t.stage}, </span>
                      {t.role_label}
                    </span>
                    <span className="font-medium">{t.name}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <Skeleton className="h-24 w-full" />
            )}
            <p className="text-xs text-muted-foreground">
              Some requests add reviewers on top, for example a Quality / Regulatory reviewer for
              each country an IVD item is sold in. Those still apply.
            </p>
          </aside>
        </div>
      </section>

      <section
        aria-label="Recent changes"
        data-testid="recent-changes"
        className="flex max-w-5xl flex-col gap-3"
      >
        <h2 className="text-lg font-semibold tracking-tight">Recent changes</h2>
        {changes === null ? (
          <Skeleton className="h-16 w-full" />
        ) : changes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No rule has been changed yet. Every change you save will be listed here.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {changes.map((c) => (
              <li key={c.id} data-testid="config-change" className="rounded-lg border bg-card p-3">
                <p className="text-sm font-medium">{c.summary}</p>
                <p className="text-xs text-muted-foreground">{formatSgt(c.at)}</p>
                <p className="mt-1 text-sm">
                  <span className="text-muted-foreground">Before: </span>
                  {c.before.join(", ") || "no approvers"}
                </p>
                <p className="text-sm">
                  <span className="text-muted-foreground">After: </span>
                  {c.after.join(", ") || "no approvers"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
