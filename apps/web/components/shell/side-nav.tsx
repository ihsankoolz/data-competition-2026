"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { activeHref, NAV_GROUPS } from "@/lib/nav";
import { cn } from "@/lib/utils";

export function SideNav() {
  const pathname = usePathname();
  const active = activeHref(pathname);

  return (
    <nav aria-label="Screens" className="flex flex-col gap-6 px-3 py-6">
      {NAV_GROUPS.map((group) => (
        <div key={group.label} className="flex flex-col gap-0.5">
          <h2 className="px-3 pb-1.5 text-xs font-medium text-muted-foreground">{group.label}</h2>
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
                      : "text-muted-foreground group-hover:text-sidebar-foreground",
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
