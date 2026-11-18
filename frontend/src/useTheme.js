import { useEffect, useState } from "react";
import { readStored, writeStored } from "./storage.mjs";

const KEY = "obshaga_theme";
const SYSTEM_DARK = "(prefers-color-scheme: dark)";
const themeFrom = (query) => query.matches ? "dark" : "light";

function readPreference() {
  const saved = readStored(KEY);
  return saved === "light" || saved === "dark" ? saved : null;
}

export function useTheme() {
  const [preference, setPreference] = useState(readPreference);
  const [systemTheme, setSystemTheme] = useState(() => themeFrom(window.matchMedia(SYSTEM_DARK)));
  const theme = preference ?? systemTheme;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (preference) return;
    const query = window.matchMedia(SYSTEM_DARK);
    const sync = () => setSystemTheme(themeFrom(query));
    query.addEventListener("change", sync);
    sync();
    return () => query.removeEventListener("change", sync);
  }, [preference]);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    writeStored(KEY, next);
    setPreference(next);
  };

  return { theme, toggle };
}
