import type { Metadata } from "next";

import { MyRequests } from "@/components/requests/my-requests";

export const metadata: Metadata = { title: "My requests" };

export default function MyRequestsPage() {
  return <MyRequests />;
}
