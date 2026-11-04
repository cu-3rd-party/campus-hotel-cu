import Brand from './Brand.jsx';
import ThemeToggle from './ThemeToggle.jsx';

export default function AccessGate({ config, failed, profileId }) {
  const appUrl = config?.telegram_app_url && (config.telegram_app_url + (Number.isSafeInteger(profileId) && profileId > 0 ? `=p${profileId}` : ''));
  return <div className="gate">
    <header className="gate__top"><Brand/><ThemeToggle compact/></header>
    <main className="gate__inner">
      <p className="gate__eyebrow">СОСЕДИ · ЛИЧНЫЙ ВХОД</p>
      <h1 className="gate__title">Знакомиться — через Telegram</h1>
      <p className="gate__subtitle">Так анкета связана с твоим аккаунтом: только ты можешь её менять и отвечать на приглашения. Открой мини-приложение, затем выбери кампус и соседей.</p>
      {!config && !failed ? <p role="status">Проверяем вход…</p> : appUrl ? <a className="access-gate__button" href={appUrl}>Открыть Соседей в Telegram →</a> : <><p role="status">Вход сейчас недоступен. Попробуй чуть позже — твоя анкета остаётся на месте.</p><button className="access-gate__button" onClick={()=>location.reload()}>Проверить ещё раз</button></>}
    </main>
  </div>;
}
