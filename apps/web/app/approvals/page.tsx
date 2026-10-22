import type { Metadata } from "next";

import { ApprovalsInbox } from "@/components/approvals/approvals-inbox";

export const metadata: Metadata = { title: "Approvals" };

export default function ApprovalsPage() {
  return <ApprovalsInbox />;
}
