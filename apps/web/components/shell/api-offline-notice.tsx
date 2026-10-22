"use client";

import { CloudOff } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { useApiOnline } from "@/lib/api/status";

const RETRY_EVERY_MS = 5_000;

function ping() {
  // Any answer flips the status back to online; the providers then reload.
  api.GET("/health").catch(() => undefined);
}

export function ApiOfflineNotice() {
  const online = useApiOnline();

  useEffect(() => {
    if (online) return;
    const id = window.setInterval(ping, RETRY_EVERY_MS);
    return () => window.clearInterval(id);
  }, [online]);

  if (online) return null;

  return (
    <div
      role="status"
      data-testid="api-offline"
      className="flex items-center justify-center gap-3 border-b bg-muted px-6 py-2 text-sm"
    >
      <CloudOff className="size-4 text-muted-foreground" />
      <span>
        Demo server offline: can&apos;t reach it right now. Screens will fill in as soon as it is
        back.
      </span>
      <Button variant="outline" size="xs" onClick={ping}>
        Try again
      </Button>
    </div>
  );
}
