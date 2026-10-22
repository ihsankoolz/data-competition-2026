"use client";

import { Check, Loader2, MessageCircleQuestion, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { announceWorkflowChange } from "@/lib/demo-events";

type RequestDetail = Schema<"RequestDetail">;
type Action = Schema<"ApprovalDecisionIn">["action"];

const COPY: Record<Exclude<Action, "approve">, { title: string; body: string; cta: string }> = {
  reject: {
    title: "Reject this request?",
    body: "The requestor sees your comment. The other approvers' tasks are closed.",
    cta: "Reject",
  },
  ask_info: {
    title: "Ask the requestor for more information",
    body: "The request waits until the requestor answers and submits it again. Say exactly what is missing.",
    cta: "Send question",
  },
};

const DONE: Record<Action, string> = {
  approve: "Approved",
  reject: "Rejected",
  ask_info: "Question sent",
};

function explain(e: unknown): string {
  if (isApiError(e) && e.status === 501)
    return "Approvals aren't available right now. Try again in a moment.";
  return isApiError(e) ? e.message : "Your decision was not saved. Please try again.";
}

/**
 * Approve / Reject / Ask for info for one approval task. A comment is
 * required for the last two. Maker-checker errors from the API are shown as
 * the API words them.
 */
export function DecisionActions({
  taskId,
  title,
  onDecided,
  size = "default",
}: {
  taskId: string;
  title: string;
  onDecided: (detail: RequestDetail) => void;
  size?: "default" | "sm";
}) {
  const [busy, setBusy] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState<Exclude<Action, "approve"> | null>(null);
  const [comment, setComment] = useState("");

  async function decide(action: Action, text?: string): Promise<boolean> {
    setBusy(action);
    setError(null);
    try {
      const detail = await api.POST("/approvals/{task_id}/decision", {
        path: { task_id: taskId },
        body: { action, comment: text?.trim() || null },
      });
      toast.success(`${DONE[action]}: ${title}`, {
        description:
          detail.state === "APPROVED"
            ? "Every approval is in. Priya can now publish it to SAP."
            : (detail.pending_with ?? []).length > 0
              ? `Still waiting on ${detail.pending_with!.join(", ")}.`
              : undefined,
      });
      announceWorkflowChange();
      onDecided(detail);
      return true;
    } catch (e) {
      setError(explain(e));
      return false;
    } finally {
      setBusy(null);
    }
  }

  const dialog = asking ? COPY[asking] : null;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size={size}
          disabled={busy !== null}
          onClick={() => void decide("approve")}
          data-testid="approve"
        >
          {busy === "approve" ? (
            <Loader2 className="animate-spin" data-icon="inline-start" />
          ) : (
            <Check data-icon="inline-start" />
          )}
          Approve
        </Button>
        <Button
          size={size}
          variant="outline"
          disabled={busy !== null}
          onClick={() => {
            setComment("");
            setError(null);
            setAsking("ask_info");
          }}
          data-testid="ask-info"
        >
          <MessageCircleQuestion data-icon="inline-start" />
          Ask for info
        </Button>
        <Button
          size={size}
          variant="ghost"
          className="text-destructive hover:text-destructive"
          disabled={busy !== null}
          onClick={() => {
            setComment("");
            setError(null);
            setAsking("reject");
          }}
          data-testid="reject"
        >
          <X data-icon="inline-start" />
          Reject
        </Button>
      </div>
      {error && (
        <p className="max-w-xl text-sm text-destructive" role="alert" data-testid="decision-error">
          {error}
        </p>
      )}

      <Dialog
        open={asking !== null}
        onOpenChange={(open) => {
          if (busy || open) return;
          setAsking(null);
          setError(null);
        }}
      >
        <DialogContent>
          {dialog && asking && (
            <form
              className="flex flex-col gap-4"
              onSubmit={async (e) => {
                e.preventDefault();
                if (!comment.trim()) return;
                if (await decide(asking, comment)) setAsking(null);
              }}
            >
              <DialogHeader>
                <DialogTitle>{dialog.title}</DialogTitle>
                <DialogDescription>{dialog.body}</DialogDescription>
              </DialogHeader>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`comment-${taskId}`}>
                  Comment <span className="font-normal text-muted-foreground">Required</span>
                </Label>
                <Textarea
                  id={`comment-${taskId}`}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  rows={4}
                  autoFocus
                  data-testid="decision-comment"
                />
              </div>
              {error && (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              )}
              <DialogFooter>
                <DialogClose asChild>
                  <Button type="button" variant="ghost" disabled={busy !== null}>
                    Cancel
                  </Button>
                </DialogClose>
                <Button
                  type="submit"
                  variant={asking === "reject" ? "destructive" : "default"}
                  disabled={busy !== null || !comment.trim()}
                  data-testid="decision-confirm"
                >
                  {busy && <Loader2 className="animate-spin" data-icon="inline-start" />}
                  {dialog.cta}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
