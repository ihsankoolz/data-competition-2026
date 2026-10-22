import type { Metadata } from "next";

import { NewRequestForm } from "@/components/request-form/new-request-form";

export const metadata: Metadata = { title: "New request" };

export default function NewRequestPage() {
  return <NewRequestForm />;
}
