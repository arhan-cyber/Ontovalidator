import { createContext, useContext, useState, type ReactNode } from "react";

/**
 * How much of a verdict's trace to render, from a one-line answer up to the
 * full retrieval/scoring internals. Purely presentational - the backend
 * always returns the full payload, this only controls what the UI shows.
 */
export type DetailLevel = "verdict" | "summary" | "detailed" | "trace";

export const DETAIL_LEVELS: DetailLevel[] = ["verdict", "summary", "detailed", "trace"];

const STORAGE_KEY = "svo:detailLevel";
const DEFAULT_LEVEL: DetailLevel = "summary";

/** True if `level` is at or above `min` in the verdict -> trace ordering. */
export function detailAtLeast(level: DetailLevel, min: DetailLevel): boolean {
  return DETAIL_LEVELS.indexOf(level) >= DETAIL_LEVELS.indexOf(min);
}

interface DetailLevelContextValue {
  level: DetailLevel;
  setLevel: (level: DetailLevel) => void;
}

const DetailLevelContext = createContext<DetailLevelContextValue | null>(null);

function readStoredLevel(): DetailLevel {
  if (typeof window === "undefined") return DEFAULT_LEVEL;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored && (DETAIL_LEVELS as string[]).includes(stored)
      ? (stored as DetailLevel)
      : DEFAULT_LEVEL;
  } catch {
    return DEFAULT_LEVEL;
  }
}

export function DetailLevelProvider({ children }: { children: ReactNode }) {
  const [level, setLevelState] = useState<DetailLevel>(readStoredLevel);

  const setLevel = (next: DetailLevel) => {
    setLevelState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage unavailable (private browsing, etc.) - in-memory state still works
      // for the rest of the session, it just won't survive a reload.
    }
  };

  return (
    <DetailLevelContext.Provider value={{ level, setLevel }}>
      {children}
    </DetailLevelContext.Provider>
  );
}

export function useDetailLevel(): DetailLevelContextValue {
  const ctx = useContext(DetailLevelContext);
  if (!ctx) {
    throw new Error("useDetailLevel must be used within a DetailLevelProvider");
  }
  return ctx;
}
