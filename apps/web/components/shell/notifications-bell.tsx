"use client";

import {
  Bell,
  BellRing,
  CircleCheck,
  CircleX,
  Forward,
  MessageCircleQuestion,
  MessagesSquare,
  SendHorizontal,
  Stamp,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useActingUserId } from "@/lib/acting-user";
import { api, type Schema } from "@/lib/api/client";
import { useApiOnline } from "@/lib/api/status";
import { DEMO_RESET_EVENT, WORKFLOW_CHANGED_EVENT } from "@/lib/demo-events";
import { formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useClock } from "./clock-provider";
import { TeamsCardPreview } from "./teams-card-preview";

type Notification = Schema<"Notification">;

const POLL_MS = 8_000;
const SHOWN = 30;
const SEEN_PREFIX = "lives-mdm.notifications-seen.";

const KIND_ICON: Record<Notification["kind"], typeof Bell> = {
  task_assigned: Stamp,
  reminder: BellRing,
  escalated: Forward,
  info_requested: MessageCircleQuestion,
  approved: CircleCheck,
  rejected: CircleX,
  published: SendHorizontal,
};

/** The API has no read flag, so "seen" is remembered per persona in this browser. */
function readSeen(user: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(SEEN_PREFIX + user);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function writeSeen(user: string, ids: string[]) {
  try {
    window.localStorage.setItem(SEEN_PREFIX + user, JSON.stringify(ids));
  } catch {
    // Blocked storage: the count resets on reload, which is fine for a demo.
  }
}

function clearAllSeen() {
  try {
    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith(SEEN_PREFIX)) window.localStorage.removeItem(key);
    }
  } catch {
    // Nothing to clear.
  }
}

export function NotificationsBell() {
  const router = useRouter();
  const user = useActingUserId();
  const online = useApiOnline();
  const { clock } = useClock();
  const [items, setItems] = useState<{ user: string; list: Notification[] } | null>(null);
  const [seen, setSeen] = useState<{ user: string; ids: Set<string> } | null>(null);
  const [teamsFor, setTeamsFor] = useState<Notification | null>(null);
  // "See it in Teams" opens its dialog only once the menu has fully closed (from the menu's
  // close-focus event, which Radix fires after the menu's layer is gone). Opening a modal dialog
  // while a modal menu is still closing can leave `pointer-events: none` on <body>.
  const pendingPreview = useRef<Notification | null>(null);
  const now = clock?.now;

  const load = useCallback(() => {
    if (!user) return;
    api.GET("/notifications").then(
      (list) => setItems({ user, list }),
      () => undefined, // The header's offline notice covers a dead server.
    );
  }, [user]);

  // Load on persona change, clock change and every few seconds.
  useEffect(() => {
    if (!user || !online) return;
    load();
    const id = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(id);
  }, [user, online, now, load]);

  useEffect(() => {
    const onChange = () => load();
    const onReset = () => {
      clearAllSeen();
      setSeen(null);
      load();
    };
    window.addEventListener(WORKFLOW_CHANGED_EVENT, onChange);
    window.addEventListener(DEMO_RESET_EVENT, onReset);
    return () => {
      window.removeEventListener(WORKFLOW_CHANGED_EVENT, onChange);
      window.removeEventListener(DEMO_RESET_EVENT, onReset);
    };
  }, [load]);

  const list = items && items.user === user ? items.list : [];
  const seenIds =
    user && seen?.user === user ? seen.ids : user ? readSeen(user) : new Set<string>();
  const unread = list.filter((n) => !seenIds.has(n.notification_id)).length;

  // Only what was on screen when the list opened counts as read; later arrivals stay new.
  const shownAtOpen = useRef<string[]>([]);
  const markShownSeen = () => {
    if (!user) return;
    const ids = [...new Set([...seenIds, ...shownAtOpen.current])];
    writeSeen(user, ids);
    setSeen({ user, ids: new Set(ids) });
  };

  return (
    <>
      <DropdownMenu
        onOpenChange={(open) => {
          // Mark as read when the list closes, so the dots stay visible while it is open.
          if (open) shownAtOpen.current = list.slice(0, SHOWN).map((n) => n.notification_id);
          else markShownSeen();
        }}
      >
        <DropdownMenuTrigger
          className="relative grid size-9 place-items-center rounded-lg outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 aria-expanded:bg-muted"
          aria-label={unread > 0 ? `Notifications, ${unread} new` : "Notifications"}
          data-testid="notifications-bell"
        >
          <Bell className="size-4.5" />
          {unread > 0 && (
            <span
              className="absolute top-1 right-1 grid h-4 min-w-4 place-items-center rounded-full bg-destructive px-1 text-[0.65rem] leading-none font-semibold text-white tabular-nums"
              data-testid="notifications-count"
            >
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="w-96 p-0"
          onCloseAutoFocus={(e) => {
            const next = pendingPreview.current;
            if (next) {
              e.preventDefault(); // focus goes into the dialog, not back to the bell
              pendingPreview.current = null;
              setTeamsFor(next);
            }
          }}
        >
          <DropdownMenuLabel className="flex items-baseline justify-between px-3 py-2.5">
            <span className="text-sm font-medium">Notifications</span>
            <span className="text-xs font-normal text-muted-foreground">
              {unread > 0 ? `${unread} new` : "All caught up"}
            </span>
          </DropdownMenuLabel>
          <DropdownMenuSeparator className="m-0" />
          <div className="max-h-[26rem] overflow-y-auto p-1" data-testid="notifications-list">
            {list.length === 0 ? (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                Nothing yet. Reminders, questions and approvals for you will show up here.
              </p>
            ) : (
              list.slice(0, SHOWN).map((n) => {
                const Icon = KIND_ICON[n.kind];
                const isNew = !seenIds.has(n.notification_id);
                return (
                  <Fragment key={n.notification_id}>
                    <DropdownMenuItem
                      className="items-start gap-3 px-3 py-2.5"
                      onSelect={() => router.push(`/requests/${n.req_id}`)}
                      data-testid="notification"
                      data-kind={n.kind}
                    >
                      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className={cn("text-sm whitespace-normal", isNew && "font-medium")}>
                          {n.message}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {n.req_id}, {formatSgt(n.created_at)}
                        </span>
                      </span>
                      {isNew && (
                        <span
                          className="mt-1.5 size-2 shrink-0 rounded-full bg-destructive"
                          aria-label="New"
                        />
                      )}
                    </DropdownMenuItem>
                    {n.teams_card && (
                      <DropdownMenuItem
                        className="-mt-1.5 gap-1.5 py-1 pr-3 pl-10 text-xs font-medium text-primary"
                        onSelect={() => {
                          pendingPreview.current = n;
                        }}
                        data-testid="see-in-teams"
                        data-req={n.req_id}
                      >
                        <MessagesSquare className="size-3.5 text-primary" />
                        See it in Teams
                      </DropdownMenuItem>
                    )}
                  </Fragment>
                );
              })
            )}
          </div>
        </DropdownMenuContent>
      </DropdownMenu>
      <TeamsCardPreview notification={teamsFor} onClose={() => setTeamsFor(null)} />
    </>
  );
}
