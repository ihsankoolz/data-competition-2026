"use client";

import { Loader2, Mail } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { formatSgt } from "@/lib/format";

type EmailSummary = Schema<"EmailSummary">;

function explain(e: unknown): string {
  if (isApiError(e) && e.status === 501) {
    return "The email list isn't switched on in this build yet. Fill in the form by hand for now.";
  }
  return isApiError(e) ? e.message : "The email list could not be loaded.";
}

/** Lists the inbox; choosing an email asks the server for a pre-filled draft. */
export function EmailPicker({
  onPick,
  picking,
}: {
  onPick: (email: EmailSummary) => Promise<boolean>;
  picking: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [emails, setEmails] = useState<EmailSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const load = () => {
    setError(null);
    api.GET("/emails").then(setEmails, (e: unknown) => setError(explain(e)));
  };

  const shown = (emails ?? []).filter((e) => {
    const q = filter.trim().toLowerCase();
    if (!q) return true;
    return [e.subject, e.from_name ?? "", e.from_address, e.snippet].some((s) =>
      s.toLowerCase().includes(q),
    );
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next && emails === null) load();
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" data-testid="create-from-email">
          <Mail data-icon="inline-start" />
          Create from email
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Create from email</DialogTitle>
          <DialogDescription>
            Pick the email that asks for this record. We fill in what it says and show the sentence
            each value came from. Bank details are never read from email.
          </DialogDescription>
        </DialogHeader>
        <Input
          placeholder="Search by subject, sender or text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Search emails"
        />
        <div className="-mx-2 max-h-[26rem] overflow-y-auto">
          {error ? (
            <div className="flex flex-col items-start gap-2 px-2 py-4 text-sm">
              <p className="text-muted-foreground">{error}</p>
              <Button variant="outline" size="sm" onClick={load}>
                Try again
              </Button>
            </div>
          ) : emails === null ? (
            <div className="flex flex-col gap-2 px-2">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : shown.length === 0 ? (
            <p className="px-2 py-4 text-sm text-muted-foreground">No email matches that search.</p>
          ) : (
            <ul className="flex flex-col">
              {shown.map((e) => (
                <li key={e.email_id}>
                  <button
                    type="button"
                    disabled={picking !== null}
                    data-testid={`email-${e.email_id}`}
                    onClick={async () => {
                      if (await onPick(e)) setOpen(false);
                    }}
                    className="flex w-full flex-col gap-0.5 rounded-lg px-2 py-2.5 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
                  >
                    <span className="flex items-baseline justify-between gap-3">
                      <span className="truncate text-sm font-medium">{e.subject}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {picking === e.email_id ? (
                          <Loader2 className="size-3.5 animate-spin" />
                        ) : (
                          formatSgt(e.received_at)
                        )}
                      </span>
                    </span>
                    <span className="truncate text-xs text-muted-foreground">
                      {e.from_name ? `${e.from_name}, ` : ""}
                      {e.from_address}: {e.snippet}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
