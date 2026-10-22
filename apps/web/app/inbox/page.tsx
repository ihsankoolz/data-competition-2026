import type { Metadata } from "next";

import { ScreenPlaceholder } from "@/components/shell/screen-placeholder";

export const metadata: Metadata = { title: "Messy inbox" };

export default function InboxPage() {
  return <ScreenPlaceholder href="/inbox" />;
}
