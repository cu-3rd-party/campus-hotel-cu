import { useTheme } from "../useTheme.js";

function ThemeIcon({ theme }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="20" height="20" aria-hidden="true">
      {theme === "dark" ? (
        <path d="M20 13A8 8 0 0 1 11 4a8 8 0 1 0 9 9Z" />
      ) : (
        <>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5" />
        </>
      )}
    </svg>
  );
}

const LABEL = { light: "Светлая", dark: "Тёмная" };

export default function ThemeToggle({ compact = false }) {
  const { theme, toggle } = useTheme();
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      title={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}
      aria-label={`Тема: ${LABEL[theme]}`}
    >
      <span className="theme-toggle__icon"><ThemeIcon theme={theme} /></span>
      {!compact && <span className="theme-toggle__label">{LABEL[theme]}</span>}
    </button>
  );
}
