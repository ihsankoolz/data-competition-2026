import type { Metadata } from "next";

import { ScreenPlaceholder } from "@/components/shell/screen-placeholder";

export const metadata: Metadata = { title: "Ops impact" };

export default function OpsPage() {
  return <ScreenPlaceholder href="/ops" />;
}
