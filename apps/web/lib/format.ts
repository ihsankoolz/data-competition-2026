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

/** Day 1 is the day the demo clock was last reset. */
export function demoDay(elapsedHours: number): number {
  return Math.floor(elapsedHours / 24) + 1;
}
