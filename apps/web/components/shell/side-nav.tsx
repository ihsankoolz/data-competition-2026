"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

import { activeHref, NAV_GROUPS } from "@/lib/nav";
import { cn } from "@/lib/utils";

function NavLinks({ active }: { active: string | null }) {
  return (
    <nav aria-label="Screens" className="flex flex-col gap-6 px-3 py-6">
      {NAV_GROUPS.map((group) => (
        <div key={group.label ?? group.items[0]?.href} className="flex flex-col gap-0.5">
          {group.label && (
            <h2 className="px-3 pb-1.5 text-xs font-medium text-sidebar-muted-foreground">
              {group.label}
            </h2>
          )}
          {group.items.map(({ href, label, icon: Icon }) => {
            const isActive = href === active;
            return (
              <Link
                key={href}
                href={href}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "group flex h-9 items-center gap-3 rounded-lg px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  isActive
                    ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
                )}
              >
                <Icon
                  className={cn(
                    "size-4 shrink-0",
                    isActive
                      ? "text-sidebar-primary"
                      : "text-sidebar-muted-foreground group-hover:text-sidebar-foreground",
                  )}
                />
                {label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

function ActiveNav() {
  const pathname = usePathname();
  return <NavLinks active={activeHref(pathname)} />;
}

/**
 * On dynamic routes (e.g. /requests/[id]) the pathname is only known at
 * request time, so the active highlight streams in; the links render at once.
 */
export function SideNav() {
  return (
    <Suspense fallback={<NavLinks active={null} />}>
      <ActiveNav />
    </Suspense>
  );
}
