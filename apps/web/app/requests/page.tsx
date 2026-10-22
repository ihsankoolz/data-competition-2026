import type { Metadata } from "next";

import { ScreenPlaceholder } from "@/components/shell/screen-placeholder";

export const metadata: Metadata = { title: "My requests" };

export default function MyRequestsPage() {
  return <ScreenPlaceholder href="/requests" />;
}
