"use client";

import { Info } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Caption } from "@/lib/analytics";

/** The (i) next to a metric: its full definition, one click or hover away (D-009). */
export function MetricInfo({ caption }: { caption: Caption }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`What is ${caption.title}?`}
          className="inline-flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <Info className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-sm text-left leading-relaxed">
        <span>
          <strong className="font-semibold">{caption.title}.</strong> {caption.caption}
        </span>
      </TooltipContent>
    </Tooltip>
  );
}

/** A section heading with its definition underneath and behind the (i). */
export function SectionHeading({
  caption,
  id,
  children,
}: {
  caption: Caption;
  id?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex max-w-2xl flex-col gap-1">
        <h2 id={id} className="flex items-center gap-1.5 text-base font-semibold tracking-tight">
          {caption.title}
          <MetricInfo caption={caption} />
        </h2>
        <p className="text-sm text-muted-foreground">{caption.caption}</p>
      </div>
      {children}
    </div>
  );
}
