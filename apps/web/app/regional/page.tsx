import type { Metadata } from "next";

import { RegionalView } from "@/components/regional/regional-view";

export const metadata: Metadata = { title: "Regional view" };

export default function RegionalPage() {
  return <RegionalView />;
}
