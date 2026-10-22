import type { Metadata } from "next";

import { ScreenPlaceholder } from "@/components/shell/screen-placeholder";

export const metadata: Metadata = { title: "Regional view" };

export default function RegionalPage() {
  return <ScreenPlaceholder href="/regional" />;
}
