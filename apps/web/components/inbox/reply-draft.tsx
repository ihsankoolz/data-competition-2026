"use client";

/**
 * A reply to the sender of a new-record email, shown as a draft under the reading. It is a fixed
 * template (lib/reply.ts), not written by the AI, and nothing is sent from here: the person copies
 * it, or opens the pre-filled form themselves.
 */
import { Check, Copy, FileInput } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { keyLabel } from "@/lib/emails";
import { buildReply, formUrlFor, replyText } from "@/lib/reply";

const COPIED_MS = 2000;

export function ReplyDraft({
  emailId,
  senderName,
  missingFields,
  onOpenForm,
}: {
  emailId: string;
  senderName: string | null;
  /** Extract keys the read found missing; labelled the same way as the reading above. */
  missingFields: string[];
  /** The same navigation as "Create request from this email". */
  onOpenForm: () => void;
}) {
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  // Only rendered after a read the person started, so the page origin is always there.
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const draft = buildReply({
    senderName,
    missingLabels: missingFields.map(keyLabel),
    formUrl: formUrlFor(origin, emailId),
  });

  async function copyReply() {
    try {
      await navigator.clipboard.writeText(replyText(draft));
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopy("idle"), COPIED_MS);
  }

  return (
    <div className="flex flex-col gap-2" data-testid="reply-draft">
      <h3 className="text-sm font-semibold">Reply to sender (draft)</h3>
      <div
        className="flex flex-col gap-1.5 rounded-lg border bg-muted/30 px-3 py-2.5 text-xs leading-relaxed"
        data-testid="reply-text"
      >
        <p>{draft.greeting}</p>
        <p>{draft.intro}</p>
        {draft.missing.length > 0 && (
          <ul className="flex list-disc flex-col pl-4" data-testid="reply-missing">
            {draft.missing.map((m) => (
              <li key={m} data-testid="reply-missing-field">
                {m}
              </li>
            ))}
          </ul>
        )}
        <p>
          {draft.ask}{" "}
          <a
            href={draft.formUrl}
            onClick={(e) => {
              e.preventDefault();
              onOpenForm();
            }}
            className="break-all text-primary underline underline-offset-2"
            data-testid="reply-form-link"
          >
            {draft.formUrl}
          </a>
        </p>
        <p>{draft.signature}</p>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => void copyReply()}
          data-testid="copy-reply"
        >
          {copy === "copied" ? (
            <Check data-icon="inline-start" />
          ) : (
            <Copy data-icon="inline-start" />
          )}
          {copy === "copied" ? "Copied" : "Copy reply"}
        </Button>
        <Button variant="ghost" size="sm" onClick={onOpenForm} data-testid="open-form">
          <FileInput data-icon="inline-start" />
          Open form
        </Button>
        <span className="sr-only" role="status">
          {copy === "copied" ? "Reply copied" : ""}
        </span>
      </div>
      {copy === "failed" && (
        <p className="text-xs text-destructive" role="alert">
          Copying did not work in this browser. Select the reply above and copy it by hand.
        </p>
      )}
      <p className="text-xs text-muted-foreground" data-testid="reply-note">
        Nothing is sent from here. In production, Power Automate sends this from the MDM mailbox.
      </p>
    </div>
  );
}
