"use client";

import { Clock, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { demoDay, formatSgt } from "@/lib/format";

import { useClock } from "./clock-provider";

export function SimClock() {
  const { clock, busy, advanceDays, reset } = useClock();

  return (
    <div className="flex items-center gap-1.5" data-testid="sim-clock">
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            tabIndex={0}
            className="flex h-8 w-[19.5rem] items-center gap-2 rounded-lg px-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <Clock className="size-4 shrink-0 text-muted-foreground" />
            {clock ? (
              <>
                <span
                  className="text-sm whitespace-nowrap tabular-nums"
                  data-testid="sim-clock-time"
                >
                  {formatSgt(clock.now)} <span className="text-muted-foreground">(SGT)</span>
                </span>
                <Badge variant="secondary" className="tabular-nums" data-testid="sim-clock-day">
                  Day {demoDay(clock.elapsed_hours)}
                </Badge>
              </>
            ) : (
              <Skeleton className="h-4 flex-1" />
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-64">
          Demo time, not real time. Due dates and reminders follow this clock, so you can skip ahead
          a day to see what happens.
        </TooltipContent>
      </Tooltip>
      <Button
        variant="outline"
        size="sm"
        disabled={!clock || busy}
        onClick={() => void advanceDays(1)}
      >
        +1 day
      </Button>
      <Button variant="ghost" size="sm" disabled={!clock || busy} onClick={() => void reset()}>
        <RotateCcw data-icon="inline-start" />
        Reset clock
      </Button>
    </div>
  );
}
