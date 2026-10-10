import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";

export type FxTierPreference = "full" | "reduced" | "off" | "system";
export type FxTier = "full" | "reduced" | "off";

const STORAGE_KEY = "qwenpaw-fx-tier";
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** True when the OS requests reduced motion. */
export function isSystemReducedMotion(): boolean {
  return window.matchMedia?.(REDUCED_MOTION_QUERY).matches ?? false;
}

/**
 * Resolve the user preference to the effective tier. "system" maps to
 * "reduced" only when the OS requests reduced motion, otherwise "full".
 */
export function resolveFxTier(
  preference: FxTierPreference,
  systemReduced: boolean,
): FxTier {
  if (preference === "full") return "full";
  if (preference === "reduced") return "reduced";
  if (preference === "off") return "off";
  return systemReduced ? "reduced" : "full";
}

function getInitialPreference(): FxTierPreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (
      stored === "full" ||
      stored === "reduced" ||
      stored === "off" ||
      stored === "system"
    ) {
      return stored;
    }
  } catch {
    // ignore storage errors
  }
  return "system";
}

interface FxTierContextValue {
  /** User selected preference: full / reduced / off / system */
  fxTierPreference: FxTierPreference;
  /** Resolved effective tier after applying the system preference */
  fxTier: FxTier;
  setFxTierPreference: (preference: FxTierPreference) => void;
}

const FxTierContext = createContext<FxTierContextValue>({
  fxTierPreference: "system",
  fxTier: "full",
  setFxTierPreference: () => {},
});

export function FxTierProvider({ children }: { children: ReactNode }) {
  const [fxTierPreference, setFxTierPreferenceState] =
    useState<FxTierPreference>(getInitialPreference);
  const [systemReduced, setSystemReduced] = useState<boolean>(
    isSystemReducedMotion,
  );
  const fxTier = resolveFxTier(fxTierPreference, systemReduced);

  // Apply the effective tier to <html> so CSS variables and attribute-based
  // rules take effect across the whole console (same layer as the theme's
  // .dark-mode class on <html>).
  useEffect(() => {
    document.documentElement.dataset.fxTier = fxTier;
  }, [fxTier]);

  // Follow system reduced-motion changes when the preference is "system"
  useEffect(() => {
    if (fxTierPreference !== "system") return;

    const mq = window.matchMedia(REDUCED_MOTION_QUERY);
    const handler = (e: MediaQueryListEvent) => {
      setSystemReduced(e.matches);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [fxTierPreference]);

  const setFxTierPreference = useCallback((preference: FxTierPreference) => {
    setFxTierPreferenceState(preference);
    try {
      localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      // ignore
    }
  }, []);

  return (
    <FxTierContext.Provider
      value={{ fxTierPreference, fxTier, setFxTierPreference }}
    >
      {children}
    </FxTierContext.Provider>
  );
}

export function useFxTier(): FxTierContextValue {
  return useContext(FxTierContext);
}
