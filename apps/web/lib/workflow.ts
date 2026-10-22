/** Plain-English words for the request lifecycle (PRD §7) and approval tasks (D-007). */
import type { Schema } from "@/lib/api/client";
import { countryName } from "@/lib/format";

export type RequestState = Schema<"RequestDetail">["state"];
export type ApprovalTask = Schema<"ApprovalTask">;
export type SlaState = NonNullable<ApprovalTask["sla_state"]>;
export type Domain = Schema<"RequestDetail">["domain"];

export const STATE_TEXT: Record<RequestState, string> = {
  DRAFT: "Draft, not submitted yet",
  SUBMITTED: "Submitted",
  IN_APPROVAL: "Waiting for approvals",
  INFO_REQUESTED: "An approver asked for more information",
  REJECTED: "Rejected",
  APPROVED: "Approved, ready to publish to SAP",
  PUBLISHED_INACTIVE: "Sent to SAP, being checked",
  ACTIVE: "Live in SAP",
  LINKED_TO_EXISTING: "Linked to an existing record",
};

/** Badge tone per state: green when done, amber when someone must act, red when stopped. */
export function stateTone(state: RequestState): "good" | "wait" | "bad" | "neutral" {
  if (state === "ACTIVE" || state === "LINKED_TO_EXISTING" || state === "APPROVED") return "good";
  if (state === "REJECTED") return "bad";
  if (state === "INFO_REQUESTED" || state === "IN_APPROVAL" || state === "SUBMITTED") return "wait";
  return "neutral";
}

export const TASK_TEXT: Record<ApprovalTask["status"], string> = {
  waiting: "Not started yet",
  pending: "Deciding",
  approved: "Approved",
  rejected: "Rejected",
  info_requested: "Asked for more information",
  cancelled: "Not needed",
};

const ROLE_TEXT: Record<ApprovalTask["role"], string> = {
  requestor: "Requestor",
  bu_head: "BU Head",
  finance: "Finance",
  quality_regulatory: "Quality/Regulatory",
  business_support: "Business Support",
  mdm_analyst: "MDM publish to SAP",
};

export function roleLabel(task: Pick<ApprovalTask, "role" | "country">): string {
  const base = ROLE_TEXT[task.role];
  return task.role === "quality_regulatory" && task.country
    ? `${base}, ${countryName(task.country)}`
    : base;
}

export const SLA_TEXT: Record<SlaState, string> = {
  on_track: "On track",
  reminded: "Reminder sent",
  overdue: "Overdue",
  done: "Done",
};

export const SLA_HELP =
  "Each approver has 2 working days on the demo clock. A reminder goes out after 1 day; after 2 days the task is overdue and passed to a backup approver.";

export const DOMAIN_TEXT: Record<Domain, string> = {
  customer: "Customer",
  vendor: "Vendor",
  item: "Item",
  cost_center: "Cost Center",
};

/** "Customer request, SPD Singapore" */
export function requestContext(r: { domain: Domain; entity: string; country: string }): string {
  return `${DOMAIN_TEXT[r.domain]} request, ${r.entity} ${countryName(r.country)}`;
}
