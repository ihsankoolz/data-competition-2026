import { AlarmClock, BellRing, CircleCheck, Clock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
  type RequestState,
  SLA_HELP,
  SLA_TEXT,
  type SlaState,
  STATE_TEXT,
  stateTone,
} from "@/lib/workflow";

const TONE_CLASS = {
  good: "bg-success/12 text-success-foreground",
  wait: "bg-warning/15 text-warning-foreground",
  bad: "bg-destructive/10 text-destructive",
  neutral: "bg-secondary text-secondary-foreground",
} as const;

export function StateBadge({ state, className }: { state: RequestState; className?: string }) {
  return (
    <Badge
      variant="secondary"
      className={cn(TONE_CLASS[stateTone(state)], className)}
      data-testid="request-state"
      data-state={state}
    >
      {STATE_TEXT[state]}
    </Badge>
  );
}

const SLA_ICON = { on_track: Clock, reminded: BellRing, overdue: AlarmClock, done: CircleCheck };
const SLA_TONE: Record<SlaState, keyof typeof TONE_CLASS> = {
  on_track: "neutral",
  reminded: "wait",
  overdue: "bad",
  done: "good",
};

/** On track / Reminder sent / Overdue, from the simulated clock. The tooltip explains the rule. */
export function SlaBadge({ state }: { state: SlaState }) {
  const Icon = SLA_ICON[state];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant="secondary"
          tabIndex={0}
          className={TONE_CLASS[SLA_TONE[state]]}
          data-testid="sla-badge"
          data-sla={state}
        >
          <Icon data-icon="inline-start" />
          {SLA_TEXT[state]}
        </Badge>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-72">
        {SLA_HELP}
      </TooltipContent>
    </Tooltip>
  );
}
