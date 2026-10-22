import { navItem } from "@/lib/nav";

/** Stand-in for a screen that has not been built yet. */
export function ScreenPlaceholder({ href }: { href: string }) {
  const { label, description, icon: Icon } = navItem(href);
  return (
    <div className="flex flex-col gap-8">
      <header className="flex max-w-3xl flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">{label}</h1>
        <p className="text-base text-muted-foreground">{description}</p>
      </header>
      <section
        aria-label={`${label} (not built yet)`}
        className="flex min-h-80 flex-col items-center justify-center gap-3 rounded-xl border border-dashed text-center"
      >
        <Icon className="size-6 text-muted-foreground" />
        <p className="max-w-sm text-sm text-muted-foreground">
          This screen is being built. It will show up here, using the seeded demo data.
        </p>
      </section>
    </div>
  );
}
