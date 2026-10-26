import type { Metadata } from "next";

import { ApprovalRulesEditor } from "@/components/admin/approval-rules-editor";
import { HistoryCheck } from "@/components/admin/history-check";
import { RequiredFieldsEditor } from "@/components/admin/required-fields-editor";
import { navItem } from "@/lib/nav";

export const metadata: Metadata = { title: "Admin \& config" };

export default function AdminPage() {
  const { label, description } = navItem("/admin");
  return (
    <div className="flex flex-col gap-8">
      <header className="flex max-w-3xl flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">{label}</h1>
        <p className="text-base text-muted-foreground">{description}</p>
      </header>
      <ApprovalRulesEditor />
      <RequiredFieldsEditor />
      <HistoryCheck />
    </div>
  );
}
