import type { Metadata } from "next";

import { OpsImpactCard } from "@/components/ops/ops-impact-card";

export const metadata: Metadata = { title: "Ops impact" };

export default function OpsPage() {
  return (
    <div className="flex flex-col gap-8">
      <header className="flex max-w-3xl flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Ops impact</h1>
        <p className="text-base text-muted-foreground">
          What parallel approvals and checks at entry would do to request cycle time. We replayed
          every past request in the synthetic history through the new rules.
        </p>
      </header>
      <OpsImpactCard />
    </div>
  );
}
