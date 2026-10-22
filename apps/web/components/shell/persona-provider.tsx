"use client";

import { createContext, use, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  actAsOtherPerson,
  DEFAULT_ACTING_USER,
  type OtherPerson,
  setActingUserId,
  useActingUserId,
  useOtherPerson,
} from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { useApiOnline } from "@/lib/api/status";

export type Persona = Schema<"Persona">;

type PersonaContextValue = {
  /** All seeded personas, or null while loading / if the API is down. */
  personas: Persona[] | null;
  /** The persona the app is acting as, once personas have loaded. */
  persona: Persona | null;
  setPersona: (userId: string) => void;
  /** Act as a seeded person outside the persona list (e.g. a pending approver). */
  actAsOther: (p: OtherPerson) => void;
  /** True when acting as someone outside the persona list. */
  isOther: boolean;
  error: string | null;
  reload: () => void;
};

const PersonaContext = createContext<PersonaContextValue | null>(null);

export function PersonaProvider({ children }: { children: React.ReactNode }) {
  const actingUserId = useActingUserId();
  const online = useApiOnline();
  const [personas, setPersonas] = useState<Persona[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [attempt, setAttempt] = useState(0);

  // Load on mount, on "reload", and when the server comes back online.
  useEffect(() => {
    if (!online) return;
    let current = true;
    api.GET("/personas").then(
      (list) => {
        if (!current) return;
        setPersonas(list);
        setError(null);
      },
      (e: unknown) => {
        if (!current) return;
        setError(isApiError(e) ? e.message : "Could not load the people list.");
      },
    );
    return () => {
      current = false;
    };
  }, [online, attempt]);

  const other = useOtherPerson();
  const known = personas && actingUserId ? personas.find((p) => p.user_id === actingUserId) : null;
  const otherPersona: Persona | null =
    !known && other && other.user_id === actingUserId
      ? {
          user_id: other.user_id,
          name: other.name,
          title: other.title,
          roles: [],
          entity: "Group",
          country: other.country ?? "",
        }
      : null;
  const unknownId = !!personas && !!actingUserId && !known && !otherPersona;

  // A stored id that is neither a persona nor a remembered person: clear it and say so.
  useEffect(() => {
    if (!unknownId || !personas) return;
    const fallback = personas.find((p) => p.user_id === DEFAULT_ACTING_USER) ?? personas[0];
    if (!fallback) return;
    setActingUserId(fallback.user_id);
    toast.info(`Now acting as ${fallback.name}`, {
      id: "persona-fallback",
      description: "The person chosen earlier isn't in this demo any more.",
    });
  }, [unknownId, personas]);

  const persona = unknownId ? null : (known ?? otherPersona ?? null);

  return (
    <PersonaContext
      value={{
        personas,
        persona,
        setPersona: setActingUserId,
        actAsOther: actAsOtherPerson,
        isOther: !!otherPersona,
        error,
        reload: () => setAttempt((n) => n + 1),
      }}
    >
      {children}
    </PersonaContext>
  );
}

export function usePersona(): PersonaContextValue {
  const ctx = use(PersonaContext);
  if (!ctx) throw new Error("usePersona must be used inside PersonaProvider");
  return ctx;
}
