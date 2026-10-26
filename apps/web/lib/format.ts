const COUNTRY_NAMES: Record<string, string> = {
  SG: "Singapore",
  MY: "Malaysia",
  ID: "Indonesia",
  VN: "Vietnam",
  TH: "Thailand",
};

export function countryName(iso2: string): string {
  return COUNTRY_NAMES[iso2] ?? iso2;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const SGT_OFFSET_HOURS = 8;

/**
 * "Mon 5 Oct 2026, 9:00 am" in Singapore time, whatever the viewer's
 * timezone. Built by hand so the output is identical on every machine.
 */
export function formatSgt(iso: string): string {
  const d = new Date(new Date(iso).getTime() + SGT_OFFSET_HOURS * 3_600_000);
  const hour24 = d.getUTCHours();
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
  const minutes = String(d.getUTCMinutes()).padStart(2, "0");
  const period = hour24 < 12 ? "am" : "pm";
  return `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${hour12}:${minutes} ${period}`;
}

/**
 * A due time for an approver: SGT words, plus the approver's own local time
 * when it differs ("Wed 7 Oct 2026, 9:00 am SGT, 8:00 am in Vietnam"). The
 * local part comes from the API (`due_local`), so it matches the notification
 * text word for word. SG and MY approvers see the SGT words only.
 */
export function formatDue(iso: string, dueLocal?: string | null): string {
  return dueLocal ? `${formatSgt(iso)} SGT, ${dueLocal}` : formatSgt(iso);
}

/** Day 1 is the day the demo clock was last reset. */
export function demoDay(elapsedHours: number): number {
  return Math.floor(elapsedHours / 24) + 1;
}

/** "15 Aug 2026" from "2026-08-15"; anything else is returned as it is. */
export function formatDay(isoDate: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!m) return isoDate;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}`;
}

/** Today's date ("2026-10-05") on the demo clock, in Singapore time. */
export function sgtDay(iso: string): string {
  const d = new Date(new Date(iso).getTime() + SGT_OFFSET_HOURS * 3_600_000);
  return d.toISOString().slice(0, 10);
}
