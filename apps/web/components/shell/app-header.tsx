"use client";

import { Separator } from "@/components/ui/separator";

import { ApiOfflineNotice } from "./api-offline-notice";
import { NotificationsBell } from "./notifications-bell";
import { PersonaSwitcher } from "./persona-switcher";
import { ResetDemoButton } from "./reset-demo-button";
import { SimClock } from "./sim-clock";

function Wordmark() {
  return (
    <div className="flex items-center gap-3">
      <span
        aria-hidden
        className="grid size-8 place-items-center rounded-lg bg-sidebar-primary text-sm font-semibold text-sidebar-primary-foreground"
      >
        L
      </span>
      <div className="flex flex-col leading-tight">
        <span className="text-sm font-semibold">Lives Group Master Data</span>
        <span className="text-xs text-sidebar-muted-foreground">Messy in, clean out</span>
      </div>
    </div>
  );
}

export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 col-span-2 border-b bg-background">
      <div className="flex h-16 items-center gap-6 pr-4">
        {/* Same colours as the sidebar below it, so the two read as one column (D-023). The
            border-r lines up with the sidebar's; the 1px shadow paints over the header's
            bottom border where it meets the sidebar. */}
        <div
          className="flex w-60 shrink-0 items-center self-stretch border-r bg-sidebar pl-5 text-sidebar-foreground shadow-[0_1px_0_var(--sidebar)]"
          data-testid="logo-block"
        >
          <Wordmark />
        </div>
        <div className="ml-auto flex items-center gap-4">
          <SimClock />
          <Separator orientation="vertical" className="h-6!" />
          <ResetDemoButton />
          <Separator orientation="vertical" className="h-6!" />
          <NotificationsBell />
          <PersonaSwitcher />
        </div>
      </div>
      <ApiOfflineNotice />
    </header>
  );
}
