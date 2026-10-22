import { SectionHeading } from "@/components/analytics/metric-info";
import type { Caption } from "@/lib/analytics";
import type { Schema } from "@/lib/api/client";

type Action = Schema<"RecommendedAction">;

export function ActionsList({ actions, caption }: { actions: Action[]; caption: Caption }) {
  return (
    <section aria-labelledby="actions-title" className="flex flex-col gap-4" data-testid="actions">
      <SectionHeading id="actions-title" caption={caption} />
      <ol className="flex flex-col gap-4">
        {actions.map((a, i) => (
          <li key={a.title} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-2">
            <span
              aria-hidden
              className="mt-0.5 flex size-6 items-center justify-center rounded-full bg-foreground text-xs font-semibold text-background tabular-nums"
            >
              {i + 1}
            </span>
            <div className="flex flex-col gap-1">
              <p className="text-sm font-semibold">{a.title}</p>
              <p className="text-sm leading-relaxed text-muted-foreground">{a.detail}</p>
              <p className="text-xs text-muted-foreground">Based on: {a.evidence}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
