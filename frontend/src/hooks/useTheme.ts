// Light/dark theme (NFR-006, task T028). Defaults to the OS preference; the choice is a
// per-viewer convenience kept in localStorage, wrapped in try/catch (storage may be blocked).
import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "codecompass.theme";

function readStored(): Theme | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(() => readStored() ?? systemTheme());

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      try {
        window.localStorage.setItem(KEY, next);
      } catch {
        // storage unavailable: the choice lasts for this page view only
      }
      return next;
    });
  }, []);

  return { theme, toggle };
}
