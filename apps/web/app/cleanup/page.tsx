import type { Metadata } from "next";

import { CleanupQueue } from "@/components/cleanup/cleanup-queue";

export const metadata: Metadata = { title: "Clean-up queue" };

export default function CleanupPage() {
  return <CleanupQueue />;
}
