import type { Metadata } from "next";

import { ScreenPlaceholder } from "@/components/shell/screen-placeholder";

export const metadata: Metadata = { title: "Admin \& config" };

export default function AdminPage() {
  return <ScreenPlaceholder href="/admin" />;
}
