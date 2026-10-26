"use client";

/**
 * The demo journeys, in the order of the demo (PRD §4). Each says who to be, which email to
 * open and what to look for, and its link switches to that person before opening the screen.
 */
import { ChartColumnBig } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { setActingUserId } from "@/lib/acting-user";

export type Journey = {
  id: string;
  title: string;
  /** The persona to switch to; null when anyone can look (the regional view). */
  person: { userId: string; name: string; role: string } | null;
  /** The email to open in the inbox, and the word to search for it. */
  email?: { subject: string; search: string };
  lookFor: string[];
  href: string;
  linkText: string;
};

export const JOURNEYS: Journey[] = [
  {
    id: "marcus",
    title: "A new customer that already exists",
    person: { userId: "marcus", name: "Marcus", role: "Regional Sales, Vietnam" },
    email: { subject: "New customer - Benh vien Cho Ray", search: "Cho Ray" },
    lookFor: [
      "Read the email with AI: each detail lights up the words it came from.",
      "Create the request. The duplicate check finds Bệnh viện Chợ Rẫy, already a customer with the same tax ID.",
      "Link to the existing record. The duplicate never reaches an approver.",
    ],
    href: "/inbox",
    linkText: "Open the inbox as Marcus",
  },
  {
    id: "amy",
    title: "A new test kit sold in three countries",
    person: { userId: "amy", name: "Amy", role: "Product Manager, Singapore" },
    email: {
      subject: "New item request - Malaria Pf/Pan Antigen Rapid Test Kit",
      search: "Malaria",
    },
    lookFor: [
      "The form asks for a registration number and expiry date for each selling country.",
      "Quality/Regulatory is added for each country, and every approver gets the request at the same time.",
      "Her status page shows exactly who still has to decide, and by when.",
    ],
    href: "/inbox",
    linkText: "Open the inbox as Amy",
  },
  {
    id: "weijie",
    title: "A new vendor with bank details in the email",
    person: { userId: "weijie", name: "Wei Jie", role: "Finance Manager" },
    email: { subject: "New vendor - Precision Diagnostics Asia", search: "Precision" },
    lookFor: [
      "The bank details are removed before the AI reads the email. They go into the secure form instead.",
      "Once the request is submitted, press +1 day in the header: the system reminds Wei Jie, nobody chases by email.",
      "Switch to Daniel and the same bank details are masked. Only Finance sees them.",
      "Wei Jie approves, and the history shows who did what, and when.",
    ],
    href: "/inbox",
    linkText: "Open the inbox as Wei Jie",
  },
  {
    id: "priya",
    title: "Publish to SAP Business One",
    person: { userId: "priya", name: "Priya", role: "MDM Analyst" },
    lookFor: [
      "Approved requests wait here. One click publishes a record to SAP.",
      "What we sent and what SAP saved are shown side by side, with a green match. Nobody re-keys anything.",
    ],
    href: "/publish",
    linkText: "Open Publish to SAP as Priya",
  },
  {
    id: "regional",
    title: "A regional sales view you can trust",
    person: null,
    lookFor: [
      "Switch between before and after merge: the customer count and lost-customer alerts drop, total sales stay the same.",
      "Cross-selling only becomes visible after the merge, when each customer has one record.",
      "The forecast compares the usual Excel average with our method, including where Excel does better.",
    ],
    href: "/regional",
    linkText: "Open the regional view",
  },
];

function Initials({ name }: { name: string }) {
  const letters = name
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2);
  return (
    <span
      className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary"
      aria-hidden
    >
      {letters}
    </span>
  );
}

export function Journeys() {
  return (
    <ol className="flex flex-col divide-y rounded-xl border bg-card" data-testid="journeys">
      {JOURNEYS.map((j, i) => (
        <li
          key={j.id}
          className="grid grid-cols-[2rem_13rem_minmax(0,1fr)_auto] items-start gap-x-6 px-6 py-5"
          data-testid={`journey-${j.id}`}
        >
          <span className="pt-2 text-sm font-medium text-muted-foreground tabular-nums">
            {i + 1}
          </span>
          <div className="flex items-center gap-3">
            {j.person ? (
              <Initials name={j.person.name} />
            ) : (
              <span
                className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground"
                aria-hidden
              >
                <ChartColumnBig className="size-4" />
              </span>
            )}
            <div className="flex min-w-0 flex-col">
              <span className="text-sm font-medium" data-testid="journey-person">
                {j.person ? j.person.name : "Anyone"}
              </span>
              <span className="text-xs text-muted-foreground">
                {j.person ? j.person.role : "No need to switch"}
              </span>
            </div>
          </div>
          <div className="flex min-w-0 flex-col gap-2">
            <h3 className="text-base font-semibold tracking-tight">{j.title}</h3>
            {j.email && (
              <p className="text-sm" data-testid="journey-email">
                <span className="text-muted-foreground">Email: </span>
                &ldquo;{j.email.subject}&rdquo;
                <span className="text-muted-foreground">
                  {" "}
                  (search &ldquo;{j.email.search}&rdquo;)
                </span>
              </p>
            )}
            <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-muted-foreground">
              {j.lookFor.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </div>
          <Button asChild variant={i === 0 ? "default" : "outline"} size="sm" className="mt-1">
            <Link
              href={j.href}
              onClick={() => j.person && setActingUserId(j.person.userId)}
              data-testid={`journey-${j.id}-link`}
            >
              {j.linkText}
            </Link>
          </Button>
        </li>
      ))}
    </ol>
  );
}
