/**
 * The small slice of JSON Schema that `config/forms/*.schema.json` uses, and
 * helpers to read it. The API returns the schema as an untyped object
 * (`FormSpec.json_schema`), so this module is the one place that narrows it.
 */
import type { Schema } from "@/lib/api/client";
import { countryName, formatDay } from "@/lib/format";

export type FormSpec = Schema<"FormSpec">;
export type Domain = FormSpec["domain"];
/** The operating country of a request (one of the five). A vendor address country can be any ISO code. */
export type Country = Schema<"RequestCreate">["country"];
export type Entity = Schema<"RequestCreate">["entity"];

export const COUNTRIES: Country[] = ["SG", "MY", "ID", "VN", "TH"];
export const ENTITIES: Entity[] = ["SPD", "QTS", "QTG"];

export const ENTITY_NAMES: Record<Entity, string> = {
  SPD: "SPD (reagents and kits)",
  QTS: "QTS (equipment)",
  QTG: "QTG (service)",
};

export const FORM_DOMAINS: { value: Exclude<Domain, "cost_center">; label: string }[] = [
  { value: "customer", label: "Customer" },
  { value: "vendor", label: "Vendor" },
  { value: "item", label: "Item" },
];

export type FieldSchema = {
  type?: "string" | "integer" | "number" | "boolean" | "array" | "object";
  title?: string;
  description?: string;
  format?: string;
  enum?: (string | number)[];
  oneOf?: { const: string | number; title: string }[];
  maxLength?: number;
  minimum?: number;
  minItems?: number;
  maxItems?: number;
  items?: FieldSchema;
  properties?: Record<string, FieldSchema>;
  required?: string[];
  "x-sensitive"?: boolean;
  "x-sap-path"?: string;
  /** Code -> English label for a long enum (e.g. ISO country codes on the vendor form). */
  "x-enum-labels"?: Record<string, string>;
};

export type FormSchema = {
  title?: string;
  description?: string;
  "x-order": string[];
  "x-card-type"?: string;
  properties: Record<string, FieldSchema>;
};

export type FieldValues = Record<string, unknown>;

export function asFormSchema(spec: FormSpec): FormSchema {
  const raw = spec.json_schema as Partial<FormSchema>;
  return {
    ...raw,
    "x-order": raw["x-order"] ?? Object.keys(raw.properties ?? {}),
    properties: raw.properties ?? {},
  };
}

export type Option = { value: string | number; label: string };

/** Choices for a select: `oneOf` const/title pairs, or a plain `enum`. */
export function optionsOf(field: FieldSchema, labelFor?: (v: string) => string): Option[] | null {
  if (field.oneOf) return field.oneOf.map((o) => ({ value: o.const, label: o.title }));
  if (field.enum) {
    const labels = field["x-enum-labels"];
    return field.enum.map((v) => ({
      value: v,
      label: labels?.[String(v)] ?? (labelFor && typeof v === "string" ? labelFor(v) : String(v)),
    }));
  }
  return null;
}

/** True when a value counts as filled in for a required-field check. */
export function isFilled(value: unknown): boolean {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

/**
 * Fields the form never takes from a server response (a pre-fill or a saved
 * draft): bank details and credit terms are typed by a person only (rules 5 and 7).
 */
const NEVER_PREFILLED = new Set(["BPBankAccounts", "PayTermsGrpCode", "CreditLimit"]);

/** True for a value the API masked for this role, e.g. "••••1234" or "****". */
export function looksMasked(value: unknown): boolean {
  if (typeof value === "string") return value.includes("•") || value.includes("****");
  if (Array.isArray(value)) return value.some(looksMasked);
  if (value && typeof value === "object") return Object.values(value).some(looksMasked);
  return false;
}

/** Server fields that are safe to put in the form: no bank, no credit terms, nothing masked. */
export function prefillableFields(fields: FieldValues, schema?: FormSchema | null): FieldValues {
  const out: FieldValues = {};
  for (const [key, value] of Object.entries(fields)) {
    if (NEVER_PREFILLED.has(key)) continue;
    if (schema?.properties[key]?.["x-sensitive"]) continue;
    if (looksMasked(value)) continue;
    out[key] = value;
  }
  return out;
}

export type Registration = {
  country: Country;
  reg_no?: string;
  risk_class?: string;
  expiry_date?: string;
};

/**
 * Item: the selling countries that need a registration number. That is every
 * regulated selling country when the item is an in-vitro diagnostic.
 */
export function registrationCountries(values: FieldValues, spec: FormSpec): Country[] {
  if (values.U_IVD !== "tYES") return [];
  const selling = Array.isArray(values.selling_countries)
    ? (values.selling_countries as Country[])
    : [];
  const regulated = new Set(spec.regulated_countries ?? []);
  return COUNTRIES.filter((c) => selling.includes(c) && regulated.has(c));
}

/** Keeps one registration row per required country, preserving what was typed. */
export function syncRegistrations(values: FieldValues, spec: FormSpec): Registration[] {
  const current = Array.isArray(values.registrations)
    ? (values.registrations as Registration[])
    : [];
  return registrationCountries(values, spec).map(
    (country) => current.find((r) => r.country === country) ?? { country },
  );
}

/**
 * What each registration row must have. The server also refuses a regulated
 * IVD registration without an expiry date, so the form asks for it up front.
 */
export function requiredPerCountry(spec: FormSpec): string[] {
  const listed = spec.required_per_selling_country ?? [];
  if (spec.domain !== "item") return listed;
  return listed.includes("expiry_date") ? listed : [...listed, "expiry_date"];
}

/**
 * Registrations whose expiry date is on or before `today` (YYYY-MM-DD on the
 * demo clock), as plain-English messages keyed by country.
 */
export function expiredRegistrations(
  values: FieldValues,
  spec: FormSpec,
  today: string | null,
): Partial<Record<Country, string>> {
  const out: Partial<Record<Country, string>> = {};
  if (!today) return out;
  for (const reg of syncRegistrations(values, spec)) {
    const exp = reg.expiry_date;
    if (exp && /^\d{4}-\d{2}-\d{2}$/.test(exp) && exp <= today) {
      const name = countryName(reg.country);
      out[reg.country] =
        `The ${name} registration expired on ${formatDay(exp)}. Renew it or remove ${name} from the selling countries.`;
    }
  }
  return out;
}

/** Field keys still empty that the form must have, including per-country registration numbers. */
export function missingRequired(values: FieldValues, spec: FormSpec): string[] {
  const missing = spec.required.filter((k) => !isFilled(values[k]));
  const perCountry = requiredPerCountry(spec);
  if (spec.domain === "item" && perCountry.length > 0) {
    const regs = syncRegistrations(values, spec);
    for (const reg of regs) {
      for (const sub of perCountry) {
        if (!isFilled((reg as Record<string, unknown>)[sub])) {
          missing.push(`registrations.${reg.country}.${sub}`);
        }
      }
    }
  }
  return missing;
}
