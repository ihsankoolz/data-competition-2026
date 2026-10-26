"use client";

import { Download, Info } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { formatSgt } from "@/lib/format";
import { cn } from "@/lib/utils";

type Notification = Schema<"Notification">;
type Card = Schema<"AdaptiveCard">;
type Element = Card["body"][number];
type Action = Card["actions"][number];

/**
 * A preview of the Teams reminder for one approval: the Adaptive Card JSON the API
 * builds (`GET /notifications/{id}/teams-card`), drawn with plain elements in the
 * style of a Teams chat message. No Adaptive Cards renderer: the card only uses
 * TextBlock, FactSet, Action.Submit and Action.OpenUrl, so each is mapped by hand.
 *
 * Nothing is sent from here and the buttons do not decide anything.
 */
export function TeamsCardPreview({
  notification,
  onClose,
}: {
  notification: Notification | null;
  onClose: () => void;
}) {
  const id = notification?.notification_id ?? null;
  const [loaded, setLoaded] = useState<{ id: string; card?: Card; error?: string } | null>(null);
  const [pressed, setPressed] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const ctrl = new AbortController();
    api
      .GET("/notifications/{notification_id}/teams-card", {
        path: { notification_id: id },
        signal: ctrl.signal,
      })
      .then(
        (card) => setLoaded({ id, card }),
        (e: unknown) => {
          if (ctrl.signal.aborted) return;
          setLoaded({
            id,
            error: isApiError(e) ? e.message : "The card could not be loaded. Try again.",
          });
        },
      );
    return () => ctrl.abort();
  }, [id]);

  const current = loaded && loaded.id === id ? loaded : null;
  const card = current?.card;

  const download = () => {
    if (!card || !notification) return;
    const blob = new Blob([JSON.stringify(card, null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `teams-card-${notification.req_id}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000); // after the download starts
  };

  return (
    <Dialog
      open={notification !== null}
      onOpenChange={(open) => {
        if (!open) {
          setPressed(null);
          onClose();
        }
      }}
    >
      <DialogContent className="gap-5 sm:max-w-xl" data-testid="teams-card-preview">
        <DialogHeader>
          <DialogTitle>How this looks in Teams</DialogTitle>
          <DialogDescription>
            The approver gets this card in a Teams chat. The due time matches the notification.
          </DialogDescription>
        </DialogHeader>

        {/* The Teams chat surface: fixed light colours, like a screenshot of Teams. */}
        <div
          className="rounded-lg bg-[#f5f5f5] p-4 text-[#242424]"
          style={{ fontFamily: '"Segoe UI", system-ui, sans-serif' }}
        >
          <div className="mb-2 flex items-center gap-2.5">
            <span
              className="grid size-8 place-items-center rounded-md bg-[#5b5fc7] text-xs font-semibold text-white"
              aria-hidden
            >
              MDM
            </span>
            <span className="text-sm font-semibold">Lives MDM approvals</span>
            {notification && (
              <span className="text-xs text-[#616161]">{formatSgt(notification.created_at)}</span>
            )}
          </div>
          <div className="ml-10.5 rounded-md border border-[#e0e0e0] bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.08)]">
            {current?.error ? (
              <p className="text-sm text-destructive" role="alert">
                {current.error}
              </p>
            ) : !card ? (
              <div className="flex flex-col gap-2" aria-label="Loading the card">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-4 w-56" />
                <Skeleton className="h-6 w-72" />
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            ) : (
              <div className="flex flex-col gap-2" data-testid="teams-card">
                {card.body.map((el, i) => (
                  <CardElement key={i} el={el} />
                ))}
                <div className="mt-2 flex flex-wrap gap-2">
                  {card.actions.map((a) => (
                    <CardButton key={a.title} action={a} onPress={() => setPressed(a.title)} />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {pressed && (
          <p
            className="-mt-2 text-xs text-muted-foreground"
            role="status"
            data-testid="teams-card-pressed"
          >
            Preview only: pressing &ldquo;{pressed}&rdquo; here does nothing.{" "}
            {pressed === "Open"
              ? "In Teams it opens this request in the MDM app."
              : "In Teams it records the approver's own decision. The AI never approves."}
          </p>
        )}

        <p className="flex gap-2 rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
          <Info className="mt-px size-3.5 shrink-0" />
          <span data-testid="teams-card-note">
            In production, Power Automate sends this card to the approver in Teams. Nothing is sent
            from here. Bank details are never put in the card. The Open link points at this demo; in
            production it is the MDM app&rsquo;s https address.
          </span>
        </p>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={download}
            disabled={!card}
            data-testid="teams-card-download"
          >
            <Download /> Download the card file (JSON)
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const TEXT_SIZE = {
  Small: "text-xs",
  Default: "text-sm",
  Medium: "text-base",
  Large: "text-lg leading-snug",
} as const;

function CardElement({ el }: { el: Element }) {
  if (el.type === "FactSet") {
    return (
      <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
        {el.facts.map((f) => (
          <div key={f.title} className="contents">
            <dt className="font-semibold">{f.title}</dt>
            <dd data-fact={f.title}>{f.value}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <p
      className={cn(
        TEXT_SIZE[el.size ?? "Default"],
        el.weight === "Bolder" && "font-semibold",
        el.isSubtle && "text-[#616161]",
        el.spacing === "None" && "-mt-2",
        el.wrap === false && "truncate",
      )}
    >
      {el.text}
    </p>
  );
}

function CardButton({ action, onPress }: { action: Action; onPress: () => void }) {
  return (
    <button
      type="button"
      onClick={onPress}
      data-testid="teams-card-action"
      data-action={action.type === "Action.Submit" ? action.data.action : "open"}
      className="min-w-24 flex-1 rounded-md border border-[#d1d1d1] bg-white px-3 py-1.5 text-sm font-semibold text-[#242424] outline-none hover:bg-[#f5f5f5] focus-visible:ring-2 focus-visible:ring-[#5b5fc7]"
    >
      {action.title}
    </button>
  );
}
