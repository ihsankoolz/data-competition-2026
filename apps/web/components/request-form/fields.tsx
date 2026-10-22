"use client";

/**
 * A small renderer for the JSON Schema subset in `config/forms/*.schema.json`.
 * One component per kind of input; `SchemaField` picks the right one.
 */
import { Lock, Mail, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { countryName } from "@/lib/format";
import { type FieldSchema, optionsOf } from "@/lib/forms/schema";
import { cn } from "@/lib/utils";

type FieldShellProps = {
  id: string;
  label: string;
  help?: string;
  required?: boolean;
  missing?: boolean;
  quote?: string;
  sensitive?: boolean;
  children: React.ReactNode;
  /** Groups (chips, rows) are labelled with a legend instead of a <label>. */
  asGroup?: boolean;
  /** Server-side problems with this field (D-018 #3), in plain English. */
  issues?: string[];
};

export function FieldShell({
  id,
  label,
  help,
  required,
  missing,
  quote,
  sensitive,
  children,
  asGroup,
  issues = [],
}: FieldShellProps) {
  const flagged = missing || issues.length > 0;
  const labelNode = (
    <span className="flex items-baseline gap-2 text-sm font-medium">
      {label}
      {required && <span className="text-xs font-normal text-muted-foreground">Required</span>}
    </span>
  );
  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 rounded-lg",
        flagged && "-mx-3 bg-destructive/5 px-3 py-2.5 ring-1 ring-destructive/30",
      )}
      data-testid={`field-${id}`}
      data-missing={missing ? "true" : undefined}
      data-issue={issues.length > 0 ? "true" : undefined}
    >
      {asGroup ? (
        <span id={`${id}-label`}>{labelNode}</span>
      ) : (
        <Label htmlFor={id} className="block">
          {labelNode}
        </Label>
      )}
      {children}
      {sensitive ? (
        <p
          className="flex items-start gap-1.5 text-xs text-muted-foreground"
          data-testid="sensitive-note"
        >
          <Lock className="mt-0.5 size-3 shrink-0" />
          {help?.includes("Finance only") ? help : `Visible to Finance only. ${help ?? ""}`.trim()}
        </p>
      ) : (
        help && <p className="text-xs text-muted-foreground">{help}</p>
      )}
      {quote && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground" data-testid="quote">
          <Mail className="mt-0.5 size-3 shrink-0" />
          <span>
            From the email: <q className="text-foreground">{quote}</q>
          </span>
        </p>
      )}
      {issues.length > 0
        ? issues.map((m) => (
            <p key={m} className="text-xs font-medium text-destructive" data-testid="field-issue">
              {m}
            </p>
          ))
        : missing && (
            <p className="text-xs font-medium text-destructive">Needed before you can submit.</p>
          )}
    </div>
  );
}

/** SAP's yes/no flags and ISO country codes, in words. */
const ENUM_WORDS: Record<string, string> = { tYES: "Yes", tNO: "No" };

function enumLabel(v: string): string {
  return ENUM_WORDS[v] ?? countryName(v);
}

type InputProps = {
  id: string;
  field: FieldSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  invalid?: boolean;
  /** Inside a row: always a single-line input. */
  compact?: boolean;
};

/** A select from `oneOf` or `enum`. Values keep their schema type (number stays number). */
function SelectInput({ id, field, value, onChange, invalid }: InputProps) {
  const options = optionsOf(field, enumLabel) ?? [];
  const current = value === undefined || value === null ? "" : String(value);
  return (
    <Select
      value={current}
      onValueChange={(v) => {
        const match = options.find((o) => String(o.value) === v);
        onChange(match ? match.value : v);
      }}
    >
      <SelectTrigger id={id} className="w-full" aria-invalid={invalid || undefined}>
        <SelectValue placeholder="Choose one" />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={String(o.value)} value={String(o.value)}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Multi-select chips for an array of enum strings (e.g. selling countries). */
function ChipsInput({ id, field, value, onChange }: InputProps) {
  const options = field.items?.enum ?? [];
  const selected = Array.isArray(value) ? (value as string[]) : [];
  return (
    <div role="group" aria-labelledby={`${id}-label`} className="flex flex-wrap gap-2">
      {options.map((raw) => {
        const v = String(raw);
        const on = selected.includes(v);
        return (
          <button
            key={v}
            type="button"
            aria-pressed={on}
            onClick={() =>
              onChange(
                on
                  ? selected.filter((s) => s !== v)
                  : options.map(String).filter((o) => o === v || selected.includes(o)),
              )
            }
            className={cn(
              "h-8 rounded-full border px-3 text-sm outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
              on
                ? "border-primary bg-primary text-primary-foreground"
                : "bg-background hover:bg-muted",
            )}
          >
            {countryName(v)}
          </button>
        );
      })}
    </div>
  );
}

function ScalarInput({ id, field, value, onChange, invalid, compact }: InputProps) {
  if (field.oneOf || field.enum) {
    return (
      <SelectInput id={id} field={field} value={value} onChange={onChange} invalid={invalid} />
    );
  }
  const text = value === undefined || value === null ? "" : String(value);
  if (!compact && field.type === "string" && (field.maxLength ?? 0) >= 200) {
    return (
      <Textarea
        id={id}
        value={text}
        rows={2}
        maxLength={field.maxLength}
        aria-invalid={invalid || undefined}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  const numeric = field.type === "number" || field.type === "integer";
  const inputType = numeric
    ? "number"
    : field.format === "email"
      ? "email"
      : field.format === "date"
        ? "date"
        : "text";
  return (
    <Input
      id={id}
      type={inputType}
      value={text}
      min={field.minimum}
      maxLength={field.maxLength}
      aria-invalid={invalid || undefined}
      onChange={(e) => {
        const raw = e.target.value;
        if (!numeric) return onChange(raw);
        onChange(raw === "" ? undefined : Number(raw));
      }}
    />
  );
}

type Row = Record<string, unknown>;

/** Rows for an array of objects (bank accounts). One row is shown to start with. */
function RowsInput({ id, field, value, onChange }: InputProps) {
  const rows: Row[] = Array.isArray(value) && value.length > 0 ? (value as Row[]) : [{}];
  const props = field.items?.properties ?? {};
  const requiredSub = new Set(field.items?.required ?? []);
  const max = field.maxItems ?? 5;

  const update = (index: number, key: string, v: unknown) =>
    onChange(rows.map((r, i) => (i === index ? { ...r, [key]: v } : r)));

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row, index) => (
        <fieldset
          key={index}
          className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border bg-muted/30 p-4"
          aria-label={`${field.title ?? "Row"} ${index + 1}`}
        >
          {Object.entries(props).map(([key, sub]) => {
            const subId = `${id}-${index}-${key}`;
            return (
              <div key={key} className="flex flex-col gap-1.5">
                <Label htmlFor={subId} className="text-xs font-medium">
                  {sub.title ?? key}
                  {requiredSub.has(key) && (
                    <span className="ml-1.5 font-normal text-muted-foreground">Required</span>
                  )}
                </Label>
                <ScalarInput
                  id={subId}
                  compact
                  field={sub}
                  value={row[key]}
                  onChange={(v) => update(index, key, v)}
                />
              </div>
            );
          })}
          {rows.length > 1 && (
            <div className="col-span-2 flex justify-end">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onChange(rows.filter((_, i) => i !== index))}
              >
                <Trash2 data-icon="inline-start" />
                Remove this account
              </Button>
            </div>
          )}
        </fieldset>
      ))}
      {rows.length < max && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="self-start"
          onClick={() => onChange([...rows, {}])}
        >
          <Plus data-icon="inline-start" />
          Add another account
        </Button>
      )}
    </div>
  );
}

export function SchemaInput(props: InputProps) {
  const { field } = props;
  if (field.type === "array" && field.items?.type === "object") return <RowsInput {...props} />;
  if (field.type === "array" && field.items?.enum) return <ChipsInput {...props} />;
  return <ScalarInput {...props} />;
}

export function isGroupField(field: FieldSchema): boolean {
  return field.type === "array";
}
