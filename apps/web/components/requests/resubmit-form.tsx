"use client";

/**
 * Edit and resubmit (D-020 #3). When an approver asks for more information, the
 * requestor sees the question above their request's fields, fixes what is asked,
 * and sends it back. Saving is PATCH /requests/{id} with only the changed fields;
 * resubmitting is the normal POST /requests/{id}/submit, so a 422 shows the same
 * plain-English problems next to each field as the new-request form does.
 */
import { Loader2, MessageCircleQuestion, SendHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { FieldShell, isGroupField, SchemaInput } from "@/components/request-form/fields";
import { RegistrationsInput } from "@/components/request-form/registrations";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isApiError, issuesOf, type Schema } from "@/lib/api/client";
import { announceWorkflowChange } from "@/lib/demo-events";
import { formatSgt } from "@/lib/format";
import {
  asFormSchema,
  type FieldValues,
  type FormSpec,
  looksMasked,
  syncRegistrations,
} from "@/lib/forms/schema";
import { cn } from "@/lib/utils";
import { roleLabel } from "@/lib/workflow";

type RequestDetail = Schema<"RequestDetail">;
type FieldIssue = Schema<"FieldIssue">;

/** Fields the operating-country bar decides; not edited here (vendors excepted, D-020 #2). */
const CONTEXT_FIELDS = new Set(["Country"]);

function issueKey(issue: FieldIssue): string {
  return issue.field.split(".")[0] ?? issue.field;
}

/** The request's own values, minus anything masked for this persona (never sent back). */
function editableValues(fields: RequestDetail["fields"]): FieldValues {
  const out: FieldValues = {};
  for (const [k, v] of Object.entries(fields)) if (!looksMasked(v)) out[k] = v;
  return out;
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

export function ResubmitForm({
  detail,
  onResubmitted,
}: {
  detail: RequestDetail;
  onResubmitted: () => void;
}) {
  const ask = detail.info_request;
  const [spec, setSpec] = useState<FormSpec | null>(null);
  const [specError, setSpecError] = useState<string | null>(null);
  const [original] = useState<FieldValues>(() => editableValues(detail.fields));
  const [values, setValues] = useState<FieldValues>(original);
  const [issues, setIssues] = useState<FieldIssue[]>(detail.issues ?? []);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (detail.domain === "cost_center") return;
    let current = true;
    api
      .GET("/forms/{domain}", {
        path: { domain: detail.domain },
        query: { country: detail.country },
      })
      .then(
        (s) => current && setSpec(s),
        (e: unknown) =>
          current && setSpecError(isApiError(e) ? e.message : "The form could not be loaded."),
      );
    return () => {
      current = false;
    };
  }, [detail.domain, detail.country]);

  const schema = spec ? asFormSchema(spec) : null;
  const vendor = detail.domain === "vendor";

  function changedFields(): FieldValues {
    const out: FieldValues = {};
    if (!schema || !spec) return out;
    for (const key of schema["x-order"]) {
      if (key === "registrations") continue;
      if (!same(values[key], original[key]) && !looksMasked(values[key])) out[key] = values[key];
    }
    if (detail.domain === "item" && "registrations" in schema.properties) {
      const regs = syncRegistrations(values, spec);
      if (!same(regs, original.registrations)) out.registrations = regs;
    }
    return out;
  }

  async function resubmit() {
    setSending(true);
    setError(null);
    try {
      const fields = changedFields();
      if (Object.keys(fields).length > 0) {
        const saved = await api.PATCH("/requests/{req_id}", {
          path: { req_id: detail.req_id },
          body: { fields },
        });
        setIssues(saved.issues ?? []);
      }
      await api.POST("/requests/{req_id}/submit", { path: { req_id: detail.req_id } });
      toast.success(ask ? `Sent back to ${ask.asked_by_name}` : "Sent back to the approvers", {
        description: "Approvals already given stay given.",
      });
      announceWorkflowChange();
      onResubmitted();
    } catch (e) {
      if (isApiError(e) && e.status === 422) setIssues(issuesOf(e));
      setError(isApiError(e) ? e.message : "The request was not sent. Please try again.");
    } finally {
      setSending(false);
    }
  }

  const setField = (key: string, v: unknown) => {
    setValues((prev) => ({ ...prev, [key]: v }));
    setIssues((prev) => prev.filter((i) => issueKey(i) !== key));
  };
  const issuesFor = (key: string) =>
    issues.filter((i) => issueKey(i) === key).map((i) => i.message);
  const keys = schema
    ? schema["x-order"].filter((k) => schema.properties[k] && (vendor || !CONTEXT_FIELDS.has(k)))
    : [];
  const placed = new Set(keys);
  const otherIssues = issues.filter((i) => !placed.has(issueKey(i)));

  return (
    <section
      className="flex flex-col gap-5 rounded-xl border border-warning/50 bg-warning/5 p-5"
      aria-label="Answer the approver"
      data-testid="resubmit-form"
    >
      <div className="flex items-start gap-3">
        <MessageCircleQuestion className="mt-0.5 size-5 shrink-0 text-warning-foreground" />
        <div className="flex flex-col gap-1">
          {ask ? (
            <>
              <p className="text-sm">
                <span className="font-medium">{ask.asked_by_name}</span>
                <span className="text-muted-foreground">
                  {" "}
                  ({roleLabel({ role: ask.role, country: null })}) asked on{" "}
                  {formatSgt(ask.asked_at)}:
                </span>
              </p>
              <blockquote
                className="border-l-2 border-warning pl-3 text-base"
                data-testid="info-question"
              >
                {ask.question}
              </blockquote>
            </>
          ) : (
            <p className="text-sm">An approver asked for more information.</p>
          )}
          <p className="text-sm text-muted-foreground">
            Change what is asked below, then send the request back. Approvals already given stay
            given; only the approver who asked decides again.
          </p>
        </div>
      </div>

      {specError ? (
        <p className="text-sm text-muted-foreground">{specError}</p>
      ) : detail.domain === "cost_center" ? null : !schema || !spec ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <fieldset className="grid grid-cols-2 gap-x-6 gap-y-5" disabled={sending}>
          <legend className="sr-only">Your request</legend>
          {keys.map((key) => {
            const field = schema.properties[key]!;
            const wide = field.type === "array" || (field.maxLength ?? 0) >= 200;
            return (
              <div key={key} className={cn(wide && "col-span-2")}>
                <FieldShell
                  id={key}
                  label={field.title ?? key}
                  help={field.description}
                  required={spec.required.includes(key)}
                  issues={issuesFor(key)}
                  sensitive={field["x-sensitive"]}
                  asGroup={isGroupField(field)}
                >
                  {key === "registrations" ? (
                    <RegistrationsInput
                      field={field}
                      values={values}
                      spec={spec}
                      showMissing={false}
                      expired={{}}
                      onChange={(rows) => setField("registrations", rows)}
                    />
                  ) : (
                    <SchemaInput
                      id={key}
                      field={field}
                      value={values[key]}
                      invalid={issuesFor(key).length > 0}
                      onChange={(v) => setField(key, v)}
                    />
                  )}
                </FieldShell>
              </div>
            );
          })}
        </fieldset>
      )}

      <div className="flex flex-col gap-2 border-t border-warning/30 pt-4">
        <div className="flex items-center gap-4">
          <Button
            onClick={() => void resubmit()}
            disabled={sending || (!spec && detail.domain !== "cost_center")}
            data-testid="resubmit"
          >
            {sending ? (
              <Loader2 className="animate-spin" data-icon="inline-start" />
            ) : (
              <SendHorizontal data-icon="inline-start" />
            )}
            Resubmit
          </Button>
          <p className="text-sm text-muted-foreground">
            Saves your changes and sends the request back to{" "}
            {ask ? ask.asked_by_name : "the approvers"}.
          </p>
        </div>
        {error && (
          <p className="text-sm text-destructive" role="alert" data-testid="resubmit-error">
            {error}
          </p>
        )}
        {otherIssues.length > 0 && (
          <ul className="flex flex-col gap-1 text-sm text-destructive" data-testid="other-issues">
            {otherIssues.map((i) => (
              <li key={`${i.field}-${i.message}`}>
                <span className="font-medium">{i.label}:</span> {i.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
