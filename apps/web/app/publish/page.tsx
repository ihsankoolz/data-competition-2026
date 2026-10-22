import type { Metadata } from "next";

import { PublishScreen } from "@/components/publish/publish-screen";

export const metadata: Metadata = { title: "Publish to SAP" };

export default function PublishPage() {
  return <PublishScreen />;
}
