"use client";

import { createContext, use, useEffect, useState } from "react";

import { DEFAULT_ACTING_USER, setActingUserId, useActingUserId } from "@/lib/acting-user";
import { api, isApiError, type Schema } from "@/lib/api/client";
import { useApiOnline } from "@/lib/api/status";

export type Persona = Schema<"Persona">;

type PersonaContextValue = {
  /** All seeded personas, or null while loading / if the API is down. */
  personas: Persona[] | null;
  /** The persona the app is acting as, once personas have loaded. */
  persona: Persona | null;
  setPersona: (userId: string) => void;
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

  const persona =
    personas && actingUserId
      ? (personas.find((p) => p.user_id === actingUserId) ??
        personas.find((p) => p.user_id === DEFAULT_ACTING_USER) ??
        personas[0] ??
        null)
      : null;

  return (
    <PersonaContext
      value={{
        personas,
        persona,
        setPersona: setActingUserId,
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
