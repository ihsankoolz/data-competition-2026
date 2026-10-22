import type { Metadata } from "next";
import { Suspense } from "react";

import { RequestStatus } from "@/components/requests/request-status";

export const metadata: Metadata = { title: "Request" };

export default function RequestPage({ params }: PageProps<"/requests/[id]">) {
  return (
    <Suspense>
      <RequestStatus params={params} />
    </Suspense>
  );
}
