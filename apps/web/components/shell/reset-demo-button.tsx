"use client";

import { DatabaseBackup, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
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
  DialogTrigger,
} from "@/components/ui/dialog";
import { api, isApiError } from "@/lib/api/client";
import { announceDemoReset } from "@/lib/demo-events";
import { clearThemePreview } from "@/lib/theme";

import { useClock } from "./clock-provider";
import { usePersona } from "./persona-provider";

function explain(e: unknown): string {
  if (isApiError(e) && e.status === 501)
    return "Reset isn't available right now. Try again in a moment.";
  return isApiError(e) ? e.message : "The demo could not be reset.";
}

/** Restores the seeded demo state (D-016) after an in-app confirmation. */
export function ResetDemoButton() {
  const router = useRouter();
  const { refresh } = useClock();
  const { reload } = usePersona();
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);

  async function reset() {
    setRunning(true);
    try {
      const result = await api.POST("/admin/reset-demo");
      // A theme preview stored in this browser must not override the theme on camera.
      clearThemePreview();
      setOpen(false);
      toast.success(`Demo reset in ${(result.duration_ms / 1000).toFixed(1)} seconds`, {
        description: result.sap_mock_reset
          ? "Requests, approvals, the clock and the SAP copy are back to the start."
          : "Requests, approvals and the clock are back to the start. The SAP copy could not be reached.",
      });
      await refresh();
      reload();
      announceDemoReset();
      router.refresh();
    } catch (e) {
      toast.error("Reset did not finish", { description: explain(e) });
    } finally {
      setRunning(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !running && setOpen(next)}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" data-testid="reset-demo">
          <DatabaseBackup data-icon="inline-start" />
          Reset demo
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset the demo?</DialogTitle>
          <DialogDescription>
            This clears every request, approval and message made since the start, puts the clock
            back to day 1 and empties the SAP copy. It takes a few seconds.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost" disabled={running}>
              Cancel
            </Button>
          </DialogClose>
          <Button onClick={() => void reset()} disabled={running} data-testid="reset-demo-confirm">
            {running && <Loader2 className="animate-spin" data-icon="inline-start" />}
            Reset demo
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
