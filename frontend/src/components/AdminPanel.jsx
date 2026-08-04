import { useEffect, useRef, useState } from "react";
import {
  adminDeleteProfile,
  fetchAdminProfiles,
  fetchAdminStats,
  sendExport,
} from "../api.js";
import { CAMPUS } from "../labels.js";
import { closeWebApp } from "../telegram.js";
import { useModalLock } from "../useModalLock.js";

// Что кладём в каждый формат — подписи честно объясняют, что человек получит.
const FORMATS = [
  ["xlsx", "Excel (.xlsx)", "Два листа: пользователи и комнаты"],
  ["csv", "CSV (.zip)", "Два файла: users.csv и rooms.csv"],
  ["json", "JSON", "Для обработки программой"],
];

// Сколько показывать «отправил», прежде чем свернуть приложение: слишком
// быстро — человек не поймёт, что произошло, слишком долго — лишнее ожидание.
const CLOSE_DELAY_MS = 900;

// Не дёргаем сервер на каждую букву в поиске.
const SEARCH_DELAY_MS = 300;

const SCOPES = [
  ["full", "Со всеми параметрами", "Анкеты целиком: быт, курс, направление"],
  ["short", "Только имена и ники", "Чтобы просто со всеми связаться"],
];

const GENDER_WORD = { male: "Парень", female: "Девушка", other: "Другое" };

/** Раздел админки: выгрузка данных или чистка анкет. */
const VIEWS = [
  ["export", "Выгрузка"],
  ["moderation", "Модерация"],
];

export default function AdminPanel({ onClose, onChanged }) {
  useModalLock();
  // Начался ли жест на подложке — иначе окно закрывалось бы от свайпа изнутри.
  const overlayDown = useRef(false);
  const [view, setView] = useState("export");
  const [stats, setStats] = useState(null);
  const [scope, setScope] = useState("full");
  const [campus, setCampus] = useState(""); // "" — оба кампус-отеля
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  // ===== Модерация =====
  const [search, setSearch] = useState("");
  const [modCampus, setModCampus] = useState("");
  const [modGender, setModGender] = useState("");
  const [people, setPeople] = useState([]);
  const [peopleBusy, setPeopleBusy] = useState(false);
  // Какую анкету собираемся удалить: удаление необратимо, поэтому в два шага.
  const [confirmId, setConfirmId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  function loadStats() {
    fetchAdminStats()
      .then(setStats)
      .catch((err) => setError(err.message));
  }

  useEffect(loadStats, []);

  // Список анкет грузим только когда открыли модерацию — и заново при смене
  // поиска или фильтров. Пауза нужна, чтобы не слать запрос на каждую букву.
  useEffect(() => {
    if (view !== "moderation") return;
    let cancelled = false;
    setPeopleBusy(true);
    const timer = setTimeout(() => {
      fetchAdminProfiles({ search, campus: modCampus, gender: modGender })
        .then((rows) => {
          if (!cancelled) setPeople(rows);
        })
        .catch((err) => {
          if (!cancelled) setError(err.message);
        })
        .finally(() => {
          if (!cancelled) setPeopleBusy(false);
        });
    }, SEARCH_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [view, search, modCampus, modGender]);

  async function handleSend(format) {
    setBusy(format);
    setError("");
    setDone("");
    try {
      const filename = await sendExport({ format, scope, campus });
      setDone(`Отправил в чат: ${filename}`);
      // Сворачиваемся, чтобы человек оказался в чате и увидел файл.
      // Небольшая пауза — чтобы успел прочитать, что всё получилось.
      setTimeout(closeWebApp, CLOSE_DELAY_MS);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function handleDelete(person) {
    setError("");
    setDone("");
    setDeletingId(person.id);
    try {
      await adminDeleteProfile(person.id);
      setPeople((prev) => prev.filter((p) => p.id !== person.id));
      setConfirmId(null);
      setDone(`Анкета «${person.name}» удалена`);
      loadStats(); // счётчики наверху сразу перестают врать
      onChanged?.(); // лента под окном тоже должна обновиться
    } catch (err) {
      setError(err.message);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div
      className="modal__overlay"
      onPointerDown={(e) => {
        overlayDown.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && overlayDown.current) onClose();
      }}
    >
      <div className="modal modal--admin">
        <div className="modal__head">
          <h2>Админка</h2>
          <button className="modal__close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal__form">
          {stats && (
            <div className="admin__stats">
              <div className="admin__stat">
                <b>{stats.profiles}</b>
                <span>анкет</span>
              </div>
              <div className="admin__stat">
                <b>{stats.with_username}</b>
                <span>с ником</span>
              </div>
              <div className="admin__stat">
                <b>{stats.with_bot}</b>
                <span>подключили бота</span>
              </div>
              <div className="admin__stat">
                <b>{stats.groups}</b>
                <span>комнат</span>
              </div>
              <div className="admin__stat">
                <b>{stats.in_groups}</b>
                <span>живут в комнатах</span>
              </div>
              {Object.entries(stats.by_campus).map(([name, count]) => (
                <div className="admin__stat" key={name}>
                  <b>{count}</b>
                  <span>{name}</span>
                </div>
              ))}
            </div>
          )}

          <div className="tabs admin__tabs">
            {VIEWS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`tabs__btn${view === value ? " tabs__btn--on" : ""}`}
                onClick={() => {
                  setView(value);
                  setError("");
                  setDone("");
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {view === "export" && (
            <>
              <div className="field">
                <span>Что выгружаем</span>
                <div className="admin__choices">
                  {SCOPES.map(([value, label, hint]) => (
                    <button
                      key={value}
                      type="button"
                      className={`admin__choice${
                        scope === value ? " admin__choice--on" : ""
                      }`}
                      onClick={() => setScope(value)}
                      aria-pressed={scope === value}
                    >
                      <b>{label}</b>
                      <span>{hint}</span>
                    </button>
                  ))}
                </div>
              </div>

              <label className="field">
                <span>Кампус-отель</span>
                <select
                  value={campus}
                  onChange={(e) => setCampus(e.target.value)}
                >
                  <option value="">Оба</option>
                  {Object.entries(CAMPUS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>

              <div className="field">
                <span>Прислать файлом в чат</span>
                <div className="admin__choices">
                  {FORMATS.map(([value, label, hint]) => (
                    <button
                      key={value}
                      type="button"
                      className="admin__choice admin__choice--action"
                      onClick={() => handleSend(value)}
                      disabled={Boolean(busy)}
                    >
                      <b>{busy === value ? "Отправляем…" : label}</b>
                      <span>{hint}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Ники есть не у всех: часть людей их скрывает или не заводила.
                  Честно предупреждаем, а не делаем вид, что выгрузка полная. */}
              {stats && stats.with_username < stats.profiles && (
                <p className="admin__note">
                  У {stats.profiles - stats.with_username} из {stats.profiles}{" "}
                  ник неизвестен — при выгрузке попробуем достать его из
                  Telegram. Получится не для всех: ник виден боту, только если
                  человек ему писал.
                </p>
              )}
            </>
          )}

          {view === "moderation" && (
            <>
              <p className="admin__note">
                Здесь видно все анкеты — обоих кампус-отелей и обоих полов.
                Удаление необратимо: человек выйдет из комнаты, его заявки
                закроются, а ему самому придёт уведомление от бота.
              </p>

              <div className="admin__search">
                <input
                  type="text"
                  placeholder="Имя, @ник или номер анкеты…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <div className="admin__search-filters">
                  <select
                    value={modCampus}
                    onChange={(e) => setModCampus(e.target.value)}
                  >
                    <option value="">Все отели</option>
                    {Object.entries(CAMPUS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <select
                    value={modGender}
                    onChange={(e) => setModGender(e.target.value)}
                  >
                    <option value="">Любой пол</option>
                    <option value="male">Парни</option>
                    <option value="female">Девушки</option>
                  </select>
                </div>
              </div>

              {peopleBusy && <p className="admin__note">Загружаем анкеты…</p>}

              {!peopleBusy && people.length === 0 && (
                <p className="admin__note">
                  {search ? "Никого не нашли." : "Анкет пока нет."}
                </p>
              )}

              <div className="admin__list">
                {people.map((person) => (
                  <div className="admin__row" key={person.id}>
                    <div className="admin__row-photo">
                      {person.photo_url ? (
                        <img src={person.photo_url} alt="" loading="lazy" />
                      ) : (
                        <span>{person.name.trim().charAt(0).toUpperCase()}</span>
                      )}
                    </div>

                    <div className="admin__row-info">
                      <b className="admin__row-name">
                        {person.name}
                        <span className="admin__row-id">#{person.id}</span>
                      </b>
                      <span className="admin__row-meta">
                        {[
                          person.telegram ? `@${person.telegram}` : "без ника",
                          GENDER_WORD[person.gender],
                          CAMPUS[person.campus],
                          person.group_id ? `комната №${person.group_id}` : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                      {person.bio && (
                        <span className="admin__row-bio">{person.bio}</span>
                      )}
                    </div>

                    {confirmId === person.id ? (
                      <div className="admin__row-confirm">
                        <button
                          type="button"
                          className="admin__row-keep"
                          onClick={() => setConfirmId(null)}
                          disabled={deletingId === person.id}
                        >
                          Оставить
                        </button>
                        <button
                          type="button"
                          className="admin__row-delete"
                          onClick={() => handleDelete(person)}
                          disabled={deletingId === person.id}
                        >
                          {deletingId === person.id ? "Удаляем…" : "Точно"}
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="admin__row-delete"
                        onClick={() => setConfirmId(person.id)}
                        disabled={Boolean(deletingId)}
                      >
                        Удалить
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {done && <p className="admin__done">✓ {done}</p>}
          {error && <p className="modal__error">{error}</p>}
        </div>
      </div>
    </div>
  );
}
