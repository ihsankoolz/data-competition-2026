"use client";

import { ChevronsUpDown } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { countryName, initials } from "@/lib/format";
import { cn } from "@/lib/utils";

import { type Persona, usePersona } from "./persona-provider";

function Monogram({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground",
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}

function where(p: Persona): string {
  if (!p.country) return p.entity;
  return p.entity === "Group"
    ? `Group, ${countryName(p.country)}`
    : `${p.entity}, ${countryName(p.country)}`;
}

export function PersonaSwitcher() {
  const { personas, persona, setPersona, isOther } = usePersona();

  if (!personas || !persona) {
    return (
      <div
        className="flex h-11 w-64 items-center gap-2.5 px-2"
        aria-busy
        aria-label="Loading people"
      >
        <Skeleton className="size-8 rounded-full" />
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-2.5 w-32" />
        </div>
      </div>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="flex h-11 w-64 items-center gap-2.5 rounded-lg px-2 text-left outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 aria-expanded:bg-muted"
        aria-label={`Acting as ${persona.name}, ${persona.title}. Switch person`}
        data-testid="persona-switcher"
      >
        <Monogram name={persona.name} />
        <span className="flex min-w-0 flex-1 flex-col leading-tight">
          <span className="flex items-baseline gap-1.5 truncate">
            <span className="text-sm font-medium">{persona.name}</span>
            <span className="truncate text-xs text-muted-foreground">{where(persona)}</span>
          </span>
          <span className="truncate text-xs text-muted-foreground">{persona.title}</span>
        </span>
        <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Act as (this demo has no login)
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup value={persona.user_id} onValueChange={setPersona}>
          {personas.map((p) => (
            <DropdownMenuRadioItem key={p.user_id} value={p.user_id} className="gap-2.5 py-1.5">
              <Monogram name={p.name} className="size-7 bg-muted text-[0.7rem] text-foreground" />
              <span className="flex min-w-0 flex-1 flex-col leading-tight">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{p.name}</span>
                  <span className="text-xs text-muted-foreground">{where(p)}</span>
                </span>
                <span className="text-xs text-muted-foreground">{p.title}</span>
              </span>
            </DropdownMenuRadioItem>
          ))}
          {isOther && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                Other people in this demo
              </DropdownMenuLabel>
              <DropdownMenuRadioItem
                value={persona.user_id}
                className="gap-2.5 py-1.5"
                data-testid="persona-other"
              >
                <Monogram name={persona.name} className="size-7 bg-muted text-[0.7rem] text-foreground" />
                <span className="flex min-w-0 flex-1 flex-col leading-tight">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium">{persona.name}</span>
                    <span className="text-xs text-muted-foreground">{where(persona)}</span>
                  </span>
                  <span className="text-xs text-muted-foreground">{persona.title}</span>
                </span>
              </DropdownMenuRadioItem>
            </>
          )}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
