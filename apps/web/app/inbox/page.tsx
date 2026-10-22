import type { Metadata } from "next";

import { MessyInbox } from "@/components/inbox/messy-inbox";

export const metadata: Metadata = { title: "Messy inbox" };

export default function InboxPage() {
  return <MessyInbox />;
}
