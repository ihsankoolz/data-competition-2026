/**
 * The five steps every request goes through, as a static row: the same steps and icons as the
 * request's journey strip (components/requests/pipeline-beam.tsx).
 */
import { Database, FileCheck2, Mail, Sparkles, Users } from "lucide-react";

export const PIPELINE_STEPS = [
  {
    id: "email",
    label: "Email",
    line: "A request arrives the way people write it: any wording, any language.",
    icon: Mail,
  },
  {
    id: "ai",
    label: "Read by AI",
    line: "The AI pulls out each detail and points at the words it came from. It only suggests.",
    icon: Sparkles,
  },
  {
    id: "golden",
    label: "Golden record",
    line: "Checked against the records we already have, so each customer exists once.",
    icon: FileCheck2,
  },
  {
    id: "approvals",
    label: "Approvals",
    line: "Every approver gets it at the same time, with reminders from the system.",
    icon: Users,
  },
  {
    id: "sap",
    label: "In SAP",
    line: "Published to SAP Business One, then read back to prove it saved correctly.",
    icon: Database,
  },
] as const;

export function PipelineSteps() {
  return (
    <ol className="grid grid-cols-5 gap-6" data-testid="home-pipeline">
      {PIPELINE_STEPS.map(({ id, label, line, icon: Icon }, i) => (
        <li key={id} className="flex flex-col gap-3" data-testid={`home-step-${id}`}>
          <div className="flex items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/10 text-primary">
              <Icon className="size-[1.125rem]" aria-hidden />
            </span>
            {i < PIPELINE_STEPS.length - 1 && (
              <span className="h-px flex-1 bg-border" aria-hidden />
            )}
          </div>
          <div className="flex flex-col gap-1">
            <h3 className="text-sm font-semibold">{label}</h3>
            <p className="text-sm leading-relaxed text-muted-foreground">{line}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
