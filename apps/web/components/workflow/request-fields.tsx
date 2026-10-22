"use client";

import { Lock } from "lucide-react";
import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { api, type Schema } from "@/lib/api/client";
import { countryName, formatDay } from "@/lib/format";
import { asFormSchema, type FormSchema, looksMasked } from "@/lib/forms/schema";
import { cn } from "@/lib/utils";

type RequestDetail = Schema<"RequestDetail">;

const WORDS: Record<string, string> = { tYES: "Yes", tNO: "No" };

function show(key: string, value: unknown, schema: FormSchema | null): string {
  if (value === null || value === undefined || value === "") return "";
  const field = schema?.properties[key];
  const option = field?.oneOf?.find((o) => o.const === value);
  if (option) return option.title;
  if (Array.isArray(value)) {
    if (value.every((v) => typeof v === "string")) {
      return (value as string[]).map((v) => (v.length === 2 ? countryName(v) : v)).join(", ");
    }
    if (key === "registrations") {
      return (value as { country?: string; reg_no?: string; expiry_date?: string }[])
        .map(
          (r) =>
            `${countryName(r.country ?? "")}: ${r.reg_no || "not given"}` +
            (r.expiry_date ? `, expires ${formatDay(r.expiry_date)}` : ", no expiry date"),
        )
        .join("; ");
    }
    return value
      .map((v) => plain(v))
      .filter(Boolean)
      .join("; ");
  }
  if (typeof value === "string")
    return WORDS[value] ?? (key === "Country" ? countryName(value) : value);
  return plain(value);
}

/** Any nested value as words: objects become "Key: value, Key: value", never "[object Object]". */
function plain(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string") return WORDS[value] ?? value;
  if (Array.isArray(value)) return value.map(plain).filter(Boolean).join("; ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => {
        const text = plain(v);
        return text ? `${k}: ${text}` : "";
      })
      .filter(Boolean)
      .join(", ");
  }
  return String(value);
}

const BANK_PARTS: [string, string][] = [
  ["BankCode", "Bank"],
  ["AccountNo", "Account number"],
  ["AccountName", "Account name"],
  ["BICSwiftCode", "SWIFT code"],
  ["IBAN", "IBAN"],
  ["Country", "Country"],
];

type BankAccount = Record<string, unknown>;

function bankAccounts(value: unknown): BankAccount[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const ok = value.every(
    (v) => v && typeof v === "object" && ("BankCode" in v || "AccountNo" in v || "IBAN" in v),
  );
  return ok ? (value as BankAccount[]) : null;
}

/** One labelled line per part of each bank account; masked values stay masked. */
function BankLines({ accounts }: { accounts: BankAccount[] }) {
  return (
    <div className="flex flex-col gap-2" data-testid="bank-lines">
      {accounts.map((a, i) => (
        <dl key={i} className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-0.5">
          {BANK_PARTS.filter(([k]) => a[k] !== undefined && a[k] !== null && a[k] !== "").map(
            ([k, label]) => {
              const v = a[k];
              const text = k === "Country" && typeof v === "string" ? countryName(v) : plain(v);
              return (
                <div key={k} className="contents">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className={cn(looksMasked(v) && "tabular-nums")}>{text}</dd>
                </div>
              );
            },
          )}
        </dl>
      ))}
    </div>
  );
}

/**
 * The request's fields as the API returns them. Bank fields arrive already
 * masked for anyone who is not Finance; this view never unmasks anything.
 */
export function RequestFields({ detail }: { detail: RequestDetail }) {
  const formKey = `${detail.domain}/${detail.country}`;
  // Which form the labels were loaded for; null schema = fall back to SAP field names.
  const [loaded, setLoaded] = useState<{ key: string; schema: FormSchema | null } | null>(null);

  useEffect(() => {
    if (detail.domain === "cost_center") return;
    let current = true;
    api
      .GET("/forms/{domain}", {
        path: { domain: detail.domain },
        query: { country: detail.country },
      })
      .then(
        (spec) => current && setLoaded({ key: formKey, schema: asFormSchema(spec) }),
        () => current && setLoaded({ key: formKey, schema: null }),
      );
    return () => {
      current = false;
    };
  }, [detail.domain, detail.country, formKey]);

  const ready = detail.domain === "cost_center" || loaded?.key === formKey;
  const schema = loaded?.key === formKey ? loaded.schema : null;

  // Wait for the labels so the list does not jump from SAP names to plain words.
  if (!ready) {
    return (
      <div className="flex flex-col gap-2.5" aria-busy aria-label="Loading the details">
        {Object.keys(detail.fields).map((k) => (
          <Skeleton key={k} className="h-4 w-full max-w-lg" />
        ))}
      </div>
    );
  }

  const order = schema ? schema["x-order"] : Object.keys(detail.fields);
  const keys = [
    ...order.filter((k) => k in detail.fields),
    ...Object.keys(detail.fields).filter((k) => !order.includes(k)),
  ].filter((k) => show(k, detail.fields[k], schema) !== "");

  if (keys.length === 0) {
    return <p className="text-sm text-muted-foreground">No details filled in yet.</p>;
  }

  return (
    <dl
      className="grid grid-cols-[minmax(9rem,14rem)_1fr] gap-x-6 gap-y-2 text-sm"
      data-testid="request-fields"
    >
      {keys.map((k) => {
        const value = detail.fields[k];
        const masked = looksMasked(value);
        const accounts = bankAccounts(value);
        const sensitive = masked || schema?.properties[k]?.["x-sensitive"];
        return (
          <div key={k} className="contents" data-testid={`value-${k}`}>
            <dt className="text-muted-foreground">{schema?.properties[k]?.title ?? k}</dt>
            <dd className={cn("min-w-0 break-words", masked && "tabular-nums")}>
              {accounts ? (
                <BankLines accounts={accounts} />
              ) : (
                show(k, value, schema)
              )}
              {sensitive && (
                <span className="ml-2 inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Lock className="size-3" />
                  {masked ? "Hidden: only Finance sees bank details" : "Finance only"}
                </span>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
