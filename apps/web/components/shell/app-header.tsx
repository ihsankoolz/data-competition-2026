"use client";

import { DatabaseBackup } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import { ApiOfflineNotice } from "./api-offline-notice";
import { PersonaSwitcher } from "./persona-switcher";
import { SimClock } from "./sim-clock";

function Wordmark() {
  return (
    <div className="flex items-center gap-3">
      <span
        aria-hidden
        className="grid size-8 place-items-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground"
      >
        L
      </span>
      <div className="flex flex-col leading-tight">
        <span className="text-sm font-semibold">Lives Group Master Data</span>
        <span className="text-xs text-muted-foreground">Messy in, clean out</span>
      </div>
    </div>
  );
}

function ResetDemoButton() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* Disabled buttons swallow hover, so the tooltip hangs off a wrapper. */}
        <span
          tabIndex={0}
          data-testid="reset-demo"
          className="inline-flex rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <Button variant="outline" size="sm" disabled>
            <DatabaseBackup data-icon="inline-start" />
            Reset demo
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom">Available once the demo data is loaded</TooltipContent>
    </Tooltip>
  );
}

export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 col-span-2 border-b bg-background">
      <div className="flex h-16 items-center gap-6 pr-4">
        <div className="w-60 shrink-0 pl-5">
          <Wordmark />
        </div>
        <div className="ml-auto flex items-center gap-4">
          <SimClock />
          <Separator orientation="vertical" className="h-6!" />
          <ResetDemoButton />
          <Separator orientation="vertical" className="h-6!" />
          <PersonaSwitcher />
        </div>
      </div>
      <ApiOfflineNotice />
    </header>
  );
}
