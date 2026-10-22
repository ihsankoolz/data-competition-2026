/** Words and text helpers for the messy inbox. */
import type { Schema } from "@/lib/api/client";
import { countryName } from "@/lib/format";

export type Interpretation = Schema<"Interpretation">;
export type Category = Interpretation["category"];

export const CATEGORY_TEXT: Record<Category, string> = {
  purchase_order: "Purchase order",
  purchase_request: "Purchase request",
  enquiry: "Enquiry",
  follow_up: "Follow-up",
  mdm_request: "New record request",
};

/** For sentences: "The AI is 90% sure this is a new record request." */
export const CATEGORY_WITH_ARTICLE: Record<Category, string> = {
  purchase_order: "a purchase order",
  purchase_request: "a purchase request",
  enquiry: "an enquiry",
  follow_up: "a follow-up",
  mdm_request: "a new record request",
};

export const CATEGORY_HELP: Record<Category, string> = {
  purchase_order: "A confirmed order from a customer. Only these count as demand.",
  purchase_request: "A customer asking to buy, not yet a confirmed order.",
  enquiry: "A question about price, stock or lead time. A leading sign of demand, not demand.",
  follow_up: "A reply or chaser on an earlier email.",
  mdm_request: "Someone asking us to create a customer, vendor or item record.",
};

export const CATEGORIES = Object.keys(CATEGORY_TEXT) as Category[];

const KEY_WORDS: Record<string, string> = {
  name: "Name",
  legal_name: "Legal name",
  tax_id: "Tax ID",
  street: "Street",
  city: "City",
  address: "Address",
  email: "Email",
  phone: "Phone",
  contact_name: "Contact",
  customer_name: "Customer",
  po_number: "PO number",
  requested_date: "Requested date",
  item_name: "Item name",
  manufacturer: "Manufacturer",
  purpose: "Purpose",
  country: "Country",
  selling_countries: "Selling countries",
  ivd: "In-vitro diagnostic",
};

/** "registration_number_SG" -> "Registration number (Singapore)" */
export function keyLabel(key: string): string {
  if (KEY_WORDS[key]) return KEY_WORDS[key];
  const cc = key.match(/_([A-Z]{2})$/);
  const base = (cc ? key.slice(0, -3) : key).replace(/_/g, " ");
  const words = base.charAt(0).toUpperCase() + base.slice(1);
  return cc ? `${words} (${countryName(cc[1]!)})` : words;
}

export function valueText(value: Schema<"QuotedValue">["value"]): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export type Segment = { text: string; key: string | null };

/**
 * Splits the body into plain and highlighted parts, one highlight per source
 * quote. Quotes are exact substrings (the API drops any that are not); a
 * case-insensitive match is the fallback. Overlaps keep the first quote.
 */
export function highlight(body: string, quotes: { key: string; quote: string }[]): Segment[] {
  const lower = body.toLowerCase();
  const ranges: { start: number; end: number; key: string }[] = [];
  for (const { key, quote } of quotes) {
    const q = quote.trim();
    if (!q) continue;
    let start = body.indexOf(q);
    if (start < 0) start = lower.indexOf(q.toLowerCase());
    if (start < 0) continue;
    const end = start + q.length;
    if (ranges.some((r) => start < r.end && end > r.start)) continue;
    ranges.push({ start, end, key });
  }
  ranges.sort((a, b) => a.start - b.start);
  const out: Segment[] = [];
  let at = 0;
  for (const r of ranges) {
    if (r.start > at) out.push({ text: body.slice(at, r.start), key: null });
    out.push({ text: body.slice(r.start, r.end), key: r.key });
    at = r.end;
  }
  if (at < body.length) out.push({ text: body.slice(at), key: null });
  return out;
}
