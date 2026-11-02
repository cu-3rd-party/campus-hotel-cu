import { useTheme } from "../useTheme.js";

function ThemeIcon({ mode }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="20" height="20" aria-hidden="true">{mode === "light" ? <><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5"/></> : mode === "dark" ? <path d="M20 13A8 8 0 0 1 11 4a8 8 0 1 0 9 9Z"/> : <><rect x="3" y="4" width="18" height="13" rx="3"/><path d="M8 21h8m-4-4v4M7 8h5"/></>}</svg>;
}
const LABEL = { system: "Системная", light: "Светлая", dark: "Тёмная" };

export default function ThemeToggle({ compact = false }) {
  const { mode, cycle } = useTheme();
  return (
    <button
      className="theme-toggle"
      onClick={cycle}
      title={`Тема: ${LABEL[mode]} — нажми, чтобы сменить`}
      aria-label={`Тема: ${LABEL[mode]}`}
    >
      <span className="theme-toggle__icon"><ThemeIcon mode={mode}/></span>
      {!compact && <span className="theme-toggle__label">{LABEL[mode]}</span>}
    </button>
  );
}
