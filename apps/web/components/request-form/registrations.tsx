"use client";

import { ShieldCheck } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { countryName } from "@/lib/format";
import {
  type FieldSchema,
  type FieldValues,
  type FormSpec,
  type Registration,
  registrationCountries,
  syncRegistrations,
} from "@/lib/forms/schema";
import { cn } from "@/lib/utils";

/**
 * Item registrations: one row per regulated selling country when the item is
 * an in-vitro diagnostic. Each row's registration number is required, and each
 * row routes a Quality/Regulatory approver for that country.
 */
export function RegistrationsInput({
  field,
  values,
  spec,
  showMissing,
  onChange,
}: {
  field: FieldSchema;
  values: FieldValues;
  spec: FormSpec;
  showMissing: boolean;
  onChange: (rows: Registration[]) => void;
}) {
  const countries = registrationCountries(values, spec);
  const rows = syncRegistrations(values, spec);
  const props = field.items?.properties ?? {};
  const required = new Set(spec.required_per_selling_country ?? []);

  if (values.U_IVD !== "tYES") {
    return (
      <p className="text-sm text-muted-foreground" data-testid="registrations-none">
        Not needed: only in-vitro diagnostic (IVD) items need a registration number per country.
      </p>
    );
  }
  if (countries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="registrations-none">
        Choose the selling countries above. Each one that regulates IVD items gets a row here.
      </p>
    );
  }

  const update = (country: string, key: string, v: string) =>
    onChange(rows.map((r) => (r.country === country ? { ...r, [key]: v } : r)));

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row) => {
        const regMissing = showMissing && required.has("reg_no") && !row.reg_no?.trim();
        return (
          <fieldset
            key={row.country}
            data-testid={`registration-${row.country}`}
            className={cn(
              "grid grid-cols-[10rem_1fr_9rem_10rem] items-end gap-3 rounded-lg border p-3",
              regMissing && "border-destructive/50 bg-destructive/5",
            )}
          >
            <legend className="sr-only">Registration in {countryName(row.country)}</legend>
            <div className="flex flex-col gap-1 pb-2">
              <span className="text-sm font-medium">{countryName(row.country)}</span>
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <ShieldCheck className="size-3" />
                Quality/Regulatory checks
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`reg-${row.country}-reg_no`} className="text-xs">
                {props.reg_no?.title ?? "Registration number"}
                <span className="ml-1.5 font-normal text-muted-foreground">Required</span>
              </Label>
              <Input
                id={`reg-${row.country}-reg_no`}
                value={row.reg_no ?? ""}
                maxLength={props.reg_no?.maxLength}
                aria-invalid={regMissing || undefined}
                onChange={(e) => update(row.country, "reg_no", e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`reg-${row.country}-risk_class`} className="text-xs">
                {props.risk_class?.title ?? "Risk class"}
              </Label>
              <Select
                value={row.risk_class ?? ""}
                onValueChange={(v) => update(row.country, "risk_class", v)}
              >
                <SelectTrigger id={`reg-${row.country}-risk_class`} className="w-full">
                  <SelectValue placeholder="Choose" />
                </SelectTrigger>
                <SelectContent>
                  {(props.risk_class?.enum ?? []).map((v) => (
                    <SelectItem key={String(v)} value={String(v)}>
                      Class {String(v)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`reg-${row.country}-expiry_date`} className="text-xs">
                {props.expiry_date?.title ?? "Expiry date"}
              </Label>
              <Input
                id={`reg-${row.country}-expiry_date`}
                type="date"
                value={row.expiry_date ?? ""}
                onChange={(e) => update(row.country, "expiry_date", e.target.value)}
              />
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}
