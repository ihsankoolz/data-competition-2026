import {
  ChartColumnBig,
  Combine,
  FilePlus2,
  Gauge,
  Inbox,
  ListChecks,
  type LucideIcon,
  SendHorizontal,
  SlidersHorizontal,
  Stamp,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  /** One plain-English line shown on the page and as the nav tooltip. */
  description: string;
  icon: LucideIcon;
};

export type NavGroup = { label: string; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Request flow",
    items: [
      {
        href: "/inbox",
        label: "Messy inbox",
        description:
          "Incoming emails sorted by type, with the key details pulled out and the sentence they came from highlighted.",
        icon: Inbox,
      },
      {
        href: "/requests/new",
        label: "New request",
        description:
          "A form that fills itself in from an email, asks only for what each country needs, and warns you before you create a duplicate.",
        icon: FilePlus2,
      },
      {
        href: "/requests",
        label: "My requests",
        description:
          "Where each request stands: who has approved, who is still to decide, and when each decision is due.",
        icon: ListChecks,
      },
      {
        href: "/approvals",
        label: "Approvals",
        description:
          "Requests waiting for your decision. Approve, reject, or ask the requestor for more information.",
        icon: Stamp,
      },
      {
        href: "/publish",
        label: "Publish to SAP",
        description:
          "Approved records sent to SAP Business One, with what we sent and what SAP saved shown side by side.",
        icon: SendHorizontal,
      },
      {
        href: "/cleanup",
        label: "Clean-up queue",
        description:
          "Existing customer records our duplicate check thinks are the same customer. Confirm each link or mark it as not the same.",
        icon: Combine,
      },
    ],
  },
  {
    label: "Results",
    items: [
      {
        href: "/regional",
        label: "Regional view",
        description:
          "Sales by country and product from confirmed purchase orders only, before and after duplicate customers are merged.",
        icon: ChartColumnBig,
      },
      {
        href: "/ops",
        label: "Ops impact",
        description:
          "How much faster requests move, how many arrive complete the first time, and how many duplicates were stopped.",
        icon: Gauge,
      },
    ],
  },
  {
    label: "Setup",
    items: [
      {
        href: "/admin",
        label: "Admin & config",
        description:
          "The rules behind the forms and approvals: which fields each country requires and who approves what.",
        icon: SlidersHorizontal,
      },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

export function navItem(href: string): NavItem {
  const item = NAV_ITEMS.find((i) => i.href === href);
  if (!item) throw new Error(`No nav item for ${href}`);
  return item;
}

/** The nav item a pathname belongs to: the longest href that matches it. */
export function activeHref(pathname: string): string | null {
  let best: string | null = null;
  for (const { href } of NAV_ITEMS) {
    const matches = pathname === href || pathname.startsWith(`${href}/`);
    if (matches && (!best || href.length > best.length)) best = href;
  }
  return best;
}
