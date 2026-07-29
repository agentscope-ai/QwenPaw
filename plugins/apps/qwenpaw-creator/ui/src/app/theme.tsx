import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type Theme = "light" | "dark" | "system";

const ThemeContext = createContext({
  theme: "system" as Theme,
  resolvedTheme: "light" as "light" | "dark",
  setTheme: (_theme: Theme) => {},
});

function resolveTheme(theme: Theme): "light" | "dark" {
  if (theme === "dark" || theme === "light") return theme;
  return typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function readStoredTheme(): string | null {
  try {
    const storage =
      typeof window === "undefined" ? undefined : window.localStorage;
    return typeof storage?.getItem === "function"
      ? storage.getItem("qwenpaw-theme")
      : null;
  } catch {
    return null;
  }
}

function persistTheme(theme: Theme): void {
  try {
    const storage =
      typeof window === "undefined" ? undefined : window.localStorage;
    if (typeof storage?.setItem === "function")
      storage.setItem("qwenpaw-theme", theme);
  } catch {
    // Storage can be unavailable in embedded/private browser contexts.
  }
}

export function ThemeProvider({
  children,
  defaultTheme = "system",
}: {
  children: ReactNode;
  defaultTheme?: Theme;
  attribute?: string;
  enableSystem?: boolean;
}) {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = readStoredTheme();
    return stored === "light" || stored === "dark" || stored === "system"
      ? stored
      : defaultTheme;
  });
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() =>
    resolveTheme(theme),
  );

  useEffect(() => {
    const next = resolveTheme(theme);
    setResolvedTheme(next);
    persistTheme(theme);
    if (typeof document !== "undefined") {
      document.documentElement.classList.toggle("dark", next === "dark");
      document.documentElement.classList.toggle("dark-mode", next === "dark");
    }
  }, [theme]);

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme }),
    [theme, resolvedTheme],
  );
  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
