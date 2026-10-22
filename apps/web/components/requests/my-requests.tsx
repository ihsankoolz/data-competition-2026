"use client";

import { FilePlus2, ListChecks } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useClock } from "@/components/shell/clock-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StateBadge } from "@/components/workflow/badges";
import { useActingUserId } from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { formatSgt } from "@/lib/format";
import { requestContext } from "@/lib/workflow";

type RequestSummary = Schema<"RequestSummary">;

/** Requests the acting person made, or has a task on, newest first. */
export function MyRequests() {
  const actingUser = useActingUserId();
  const { clock } = useClock();
  const [rows, setRows] = useState<RequestSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const now = clock?.now;

  useEffect(() => {
    if (!actingUser) return;
    let current = true;
    api.GET("/requests", { query: { scope: "mine" } }).then(
      (list) => {
        if (!current) return;
        setRows([...list].sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
        setError(null);
      },
      (e: unknown) =>
        current && setError(isApiError(e) ? e.message : "Your requests could not be loaded."),
    );
    return () => {
      current = false;
    };
  }, [actingUser, now]);

  return (
    <div className="flex flex-col gap-8">
      <header className="flex items-start justify-between gap-6">
        <div className="flex max-w-3xl flex-col gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">My requests</h1>
          <p className="text-base text-muted-foreground">
            Requests you made or are asked to decide on, and who each one is waiting for.
          </p>
        </div>
        <Button asChild>
          <Link href="/requests/new">
            <FilePlus2 data-icon="inline-start" />
            New request
          </Link>
        </Button>
      </header>
      {error ? (
        <p className="text-sm text-muted-foreground">{error}</p>
      ) : rows === null ? (
        <div className="flex flex-col gap-2" aria-busy>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed text-center">
          <ListChecks className="size-6 text-muted-foreground" />
          <p className="max-w-sm text-sm text-muted-foreground">
            No requests yet. Start one from the form, or from an email in the messy inbox.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border">
          <table className="w-full text-sm" data-testid="my-requests">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Request</th>
                <th className="px-4 py-2 font-medium">Where it stands</th>
                <th className="px-4 py-2 font-medium">Waiting on</th>
                <th className="px-4 py-2 font-medium">Last change (demo clock)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.req_id} className="border-t hover:bg-muted/30">
                  <td className="px-4 py-2.5">
                    <Link
                      href={`/requests/${r.req_id}`}
                      className="font-medium underline-offset-4 hover:underline"
                    >
                      {r.title}
                    </Link>
                    <div className="text-xs text-muted-foreground">
                      {r.req_id}, {requestContext(r)}, from {r.requestor_name}
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    <StateBadge state={r.state} />
                  </td>
                  <td className="px-4 py-2.5">{(r.pending_with ?? []).join(", ") || "Nobody"}</td>
                  <td className="px-4 py-2.5 text-muted-foreground">{formatSgt(r.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
