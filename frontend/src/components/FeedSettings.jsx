import { useEffect, useRef } from 'react';
export default function FeedSettings({ children }) {
  const ref = useRef(null);
  useEffect(() => {
    const menu = ref.current;
    const close = event => {
      if (!menu.open) return;
      if (event.type === 'keydown' && event.key === 'Escape') { menu.open = false; menu.querySelector('summary').focus(); event.preventDefault(); }
      else if (event.type === 'click' && !menu.contains(event.target)) menu.open = false;
    };
    document.addEventListener('click', close); document.addEventListener('keydown', close);
    return () => { document.removeEventListener('click', close); document.removeEventListener('keydown', close); };
  }, []);
  return <details ref={ref} className="header__settings"><summary aria-label="Настройки ленты">Лента <span aria-hidden="true">⌄</span></summary><div className="header__settings-panel">{children}</div></details>;
}
