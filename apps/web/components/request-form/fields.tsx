"use client";

/**
 * A small renderer for the JSON Schema subset in `config/forms/*.schema.json`.
 * One component per kind of input; `SchemaField` picks the right one.
 */
import { Check, ChevronsUpDown, Lightbulb, Lock, Mail, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { countryName } from "@/lib/format";
import { type FieldSchema, type Option, optionsOf } from "@/lib/forms/schema";
import { cn } from "@/lib/utils";

type FieldShellProps = {
  id: string;
  label: string;
  help?: string;
  required?: boolean;
  missing?: boolean;
  quote?: string;
  /** Why a rule suggested this value (not quoted from the email), e.g. item group. */
  suggestion?: string;
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
  suggestion,
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
      {suggestion && (
        <p
          className="flex items-start gap-1.5 text-xs text-muted-foreground"
          data-testid="suggested"
        >
          <Lightbulb className="mt-0.5 size-3 shrink-0" />
          <span>
            <span className="font-medium text-foreground">Suggested</span>, please check:{" "}
            {suggestion}
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

/** Above this many choices a plain dropdown is too long to scan: type to filter instead. */
const SEARCHABLE_FROM = 20;

/** A select from `oneOf` or `enum`. Values keep their schema type (number stays number). */
function SelectInput({ id, field, value, onChange, invalid }: InputProps) {
  const options = optionsOf(field, enumLabel) ?? [];
  const current = value === undefined || value === null ? "" : String(value);
  if (options.length > SEARCHABLE_FROM) {
    return (
      <SearchableSelect
        id={id}
        options={options}
        current={current}
        onChange={onChange}
        invalid={invalid}
      />
    );
  }
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

function SearchableSelect({
  id,
  options,
  current,
  onChange,
  invalid,
}: {
  id: string;
  options: Option[];
  current: string;
  onChange: (value: unknown) => void;
  invalid?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const selected = options.find((o) => String(o.value) === current);
  const q = query.trim().toLowerCase();
  const shown = q
    ? options.filter(
        (o) => o.label.toLowerCase().includes(q) || String(o.value).toLowerCase() === q,
      )
    : options;
  const activeIndex = Math.min(active, Math.max(0, shown.length - 1));
  const listId = `${id}-listbox`;
  const optionId = (i: number) => `${id}-option-${i}`;
  const pick = (o: Option) => {
    onChange(o.value);
    setOpen(false);
    setQuery("");
  };
  const moveTo = (i: number) => {
    setActive(i);
    document.getElementById(optionId(i))?.scrollIntoView({ block: "nearest" });
  };
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          // Start on the current choice, so Enter keeps it.
          const at = options.findIndex((o) => String(o.value) === current);
          setActive(Math.max(0, at));
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-invalid={invalid || undefined}
          className="w-full justify-between font-normal"
          data-testid={`${id}-combobox`}
        >
          <span className={cn("truncate", !selected && "text-muted-foreground")}>
            {selected ? selected.label : "Choose one"}
          </span>
          <ChevronsUpDown className="opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) min-w-64 p-0"
        onOpenAutoFocus={() => {
          window.requestAnimationFrame(() => moveTo(activeIndex));
        }}
      >
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            autoFocus
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={shown.length > 0 ? optionId(activeIndex) : undefined}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                moveTo(Math.min(shown.length - 1, activeIndex + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                moveTo(Math.max(0, activeIndex - 1));
              } else if (e.key === "Enter" && shown[activeIndex]) {
                e.preventDefault();
                pick(shown[activeIndex]);
              }
            }}
            placeholder="Type to search"
            aria-label="Search the list"
            className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>
        <ul
          id={listId}
          role="listbox"
          aria-label="Choices"
          className="max-h-64 overflow-y-auto p-1"
        >
          {shown.map((o, i) => {
            const on = String(o.value) === current;
            return (
              <li
                key={String(o.value)}
                id={optionId(i)}
                role="option"
                aria-selected={on}
                data-active={i === activeIndex ? "true" : undefined}
                onClick={() => pick(o)}
                onMouseMove={() => i !== activeIndex && setActive(i)}
                className="flex cursor-default items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm data-[active=true]:bg-muted"
              >
                <span>{o.label}</span>
                {on && <Check className="size-4" aria-hidden />}
              </li>
            );
          })}
          {shown.length === 0 && (
            <li className="px-2 py-3 text-sm text-muted-foreground">Nothing matches.</li>
          )}
        </ul>
      </PopoverContent>
    </Popover>
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
