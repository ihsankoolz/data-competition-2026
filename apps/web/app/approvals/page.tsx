import type { Metadata } from "next";

import { ScreenPlaceholder } from "@/components/shell/screen-placeholder";

export const metadata: Metadata = { title: "Approvals" };

export default function ApprovalsPage() {
  return <ScreenPlaceholder href="/approvals" />;
}
