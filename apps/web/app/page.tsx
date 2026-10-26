import type { Metadata } from "next";

import { HomeNumbers } from "@/components/home/home-numbers";
import { Journeys } from "@/components/home/journeys";
import { PipelineSteps } from "@/components/home/pipeline-steps";

export const metadata: Metadata = { title: "Start here" };

export default function HomePage() {
  return (
    <div className="flex flex-col gap-12" data-testid="home">
      <header className="flex max-w-3xl flex-col gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Start here</h1>
        <p className="text-xl leading-snug font-medium tracking-tight" data-testid="home-pitch">
          Messy emails and requests in, one clean record out, published to SAP Business One.
        </p>
        <p className="text-base text-muted-foreground">
          Each request is read when it arrives, checked against the records we already have,
          approved by everyone at once and published. The same clean customer records then give a
          regional sales view you can trust.
        </p>
      </header>

      <section aria-labelledby="steps-title" className="flex flex-col gap-5">
        <h2 id="steps-title" className="text-base font-semibold tracking-tight">
          What happens to every request
        </h2>
        <PipelineSteps />
      </section>

      <section
        aria-labelledby="numbers-title"
        className="flex flex-col gap-5 rounded-xl border bg-muted/30 px-6 py-5"
      >
        <div className="flex flex-col gap-1">
          <h2 id="numbers-title" className="text-base font-semibold tracking-tight">
            What changes
          </h2>
          <p className="text-sm text-muted-foreground">
            Calculated from the synthetic demo data. A crossed-out number is how it is today.
          </p>
        </div>
        <HomeNumbers />
      </section>

      <section aria-labelledby="journeys-title" className="flex flex-col gap-5">
        <div className="flex flex-col gap-1">
          <h2 id="journeys-title" className="text-base font-semibold tracking-tight">
            Walk through the demo
          </h2>
          <p className="text-sm text-muted-foreground">
            In this order. Each link switches to the right person first. Press Reset demo in the
            header to start again from the same data.
          </p>
        </div>
        <Journeys />
      </section>
    </div>
  );
}
