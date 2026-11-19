import { useEffect, useMemo, useRef, useState } from "react";
import {
  adminDeleteProfile,
  cancelRequest,
  changeGroupCapacity,
  createGroup,
  createInvite,
  fetchConfig,
  fetchGroupRequests,
  fetchGroups,
  fetchMyInvites,
  fetchMyRequests,
  fetchProfile,
  respondInvite,
  fetchProfiles,
  leaveGroup,
  requestJoin,
  voteRequest,
} from "./api.js";
import RoommateCard, { ProfileDetails } from "./components/RoommateCard.jsx";
import GroupCard from "./components/GroupCard.jsx";
import Filters from "./components/Filters.jsx";
import AddProfileModal from "./components/AddProfileModal.jsx";
import AdminPanel from "./components/AdminPanel.jsx";
import GenderGate from "./components/GenderGate.jsx";
import CampusGate from "./components/CampusGate.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";
import {
  CAMPUS,
  campusCapacities,
} from "./labels.js";
import { getStartParam, initWebApp, isInsideTelegram } from "./telegram.js";
import { releaseStuckLock } from "./useModalLock.js";
import { useMyProfile } from "./useMyProfile.js";
import { useDebouncedValue, useRemoteList } from "./useRemoteList.js";
import { compareHabits, sortProfilesByMatch } from "./habitMatch.js";
import { readStored, writeStored, removeStored } from "./storage.mjs";
import FeedSettings from "./components/FeedSettings.jsx";
import AccessGate from "./components/AccessGate.jsx";
import Brand from "./components/Brand.jsx";

const GENDER_KEY = "obshaga_gender";
const CAMPUS_KEY = "obshaga_campus";

const EMPTY_FILTERS = {
  search: "",
  track: "",
  course: "",
  room_capacity: "",
  sleep_schedule: "",
  smoking: "",
  tidiness: "",
  wakeup: "",
  cooking: "",
  guests: "",
  shower: "",
  temperature: "",
  noise: "",
  alcohol: "",
  snoring: "",
};

const GENDER_WORD = { male: "Парни", female: "Девушки" };
// Родительный падеж — для фразы «лента девушек».
const GENDER_OF = { male: "парней", female: "девушек" };

/** Номер анкеты из ссылки вида ?startapp=p123 (или ?profile=123 вне Telegram). */
function startProfileId() {
  const match = /^p(\d+)$/.exec(getStartParam());
  return match ? Number(match[1]) : null;
}

export default function App() {
  const [gender, setGender] = useState(
    () => readStored(GENDER_KEY) || ""
  );
  // Кампус-отель. Пока анкеты нет — выбор с первого экрана, дальше главной
  // остаётся анкета: там его и меняют, отсюда мы значение только подхватываем.
  const [campus, setCampus] = useState(
    () => readStored(CAMPUS_KEY) || ""
  );
  const [tab, setTab] = useState("singles");
  const [roomTarget, setRoomTarget] = useState(null);

  // Заявки в мою комнату (id заявки → голосуем) и мои исходящие заявки.
  const [incoming, setIncoming] = useState([]);
  const [myRequests, setMyRequests] = useState([]);
  // Мои исходящие приглашения «давай жить вместе» — чтобы не звать дважды.
  const [myInvites, setMyInvites] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [actionError, setError] = useState("");
  const [modal, setModal] = useState(null); // null | "create" | "edit" | "admin"
  const [busy, setBusy] = useState(false);
  // Админка своя только у владельцев — решает сервер по подписи Telegram.
  const [isAdmin, setIsAdmin] = useState(false);
  const [access, setAccess] = useState(null);
  const [accessFailed, setAccessFailed] = useState(false);

  const [matchingOnly, setMatchingOnly] = useState(false);

  const [targetId] = useState(startProfileId);
  const [targetError, setTargetError] = useState("");
  const [linkedProfile, setLinkedProfile] = useState(null);

  const { myProfile, loadingMe, remember, forget, reloadMe } = useMyProfile({ allowLocalFallback: Boolean(access?.development_mode) });
  const searchFilters = useDebouncedValue(filters);
  const scope = `${gender}:${campus}`;
  const identityAvailable = Boolean(access?.development_mode || isInsideTelegram());
  const enabled = Boolean(gender && campus && identityAvailable);
  const peopleFeed = useRemoteList(JSON.stringify(searchFilters), scope,
    signal => fetchProfiles({ ...searchFilters, gender, campus, recruiting: true }, { signal }), enabled);
  const roomFeed = useRemoteList(scope, scope,
    signal => fetchGroups({ gender, campus }, { signal }), enabled);
  const { data: profiles, setData: setProfiles } = peopleFeed;
  const groups = roomFeed.data;
  const matches = useMemo(() => new Map(profiles.map(profile => [
    profile.id, compareHabits(myProfile, profile),
  ])), [myProfile, profiles]);
  const sortedProfiles = useMemo(() => sortProfilesByMatch(profiles, matches), [profiles, matches]);
  const fullMatches = useMemo(() => sortedProfiles.filter(profile => matches.get(profile.id)?.percent === 100),
    [sortedProfiles, matches]);
  const shownProfiles = matchingOnly ? fullMatches : sortedProfiles;
  const activeFeed = tab === "groups" ? roomFeed : peopleFeed;
  const loading = (activeFeed.loading && !activeFeed.loaded) || (tab === "singles" && loadingMe);
  const error = actionError || activeFeed.error;
  const [visibleCount, setVisibleCount] = useState(24);
  const inboxVersion = useRef(0);
  const busyRef = useRef(false);
  useEffect(() => { setVisibleCount(24); }, [scope, searchFilters, matchingOnly]);

  function chooseGender(value) {
    writeStored(GENDER_KEY, value);
    setGender(value);
  }

  function chooseCampus(value) {
    writeStored(CAMPUS_KEY, value);
    setCampus(value);
  }

  /** Вернуться к выбору кампус-отеля. Только пока анкеты нет: дальше решает она. */
  function resetCampus() {
    removeStored(CAMPUS_KEY);
    setCampus("");
  }

  /** Заявки грузим только там, где они нужны: в свою комнату и свои исходящие. */
  async function loadRequests(me) {
    const version = ++inboxVersion.current;
    if (!me) {
      setIncoming([]);
      setMyRequests([]);
      setMyInvites([]);
      return;
    }
    try {
      const results = await Promise.allSettled([
        fetchMyRequests(me.id),
        me.group_id ? fetchGroupRequests(me.group_id) : Promise.resolve([]),
        fetchMyInvites(me.id),
      ]);
      if (version !== inboxVersion.current) return;
      const [mine, inbox, invites] = results.map(result => result.status === "fulfilled" ? result.value : []);
      setMyRequests(mine);
      setIncoming(inbox);
      setMyInvites(invites);
    } catch {
      // Заявки — не критично: лента должна работать и без них.
      setIncoming([]);
    }
  }

  // Страховка от страницы, которая осталась пришпиленной от модалки: без неё
  // приложением нельзя пользоваться совсем, а сам человек починить это не
  // может. Намеренно без списка зависимостей — проверка стоит одного чтения
  // свойства, а поймать нужно любой сценарий, включая те, которых мы не знаем.
  useEffect(() => {
    releaseStuckLock();
  });

  // Если сайт открыт внутри Telegram — разворачиваем окно Mini App.
  useEffect(() => {
    initWebApp();
    fetchConfig()
      .then((cfg) => { setAccess(cfg); setIsAdmin(Boolean(cfg.is_admin)); })
      .catch(() => { setIsAdmin(false); setAccessFailed(true); });
  }, []);

  // Анкета — источник правды про кампус-отель: сменили его в анкете (или зашли с
  // другого устройства) — лента должна переехать следом.
  useEffect(() => {
    if (myProfile?.campus && myProfile.campus !== campus) {
      chooseCampus(myProfile.campus);
    }
  }, [myProfile, campus]);

  // Фильтр «комната на 4» пережил переезд в «Облако» — там таких нет, и лента
  // молча оказалась бы пустой. Сбрасываем сами.
  useEffect(() => {
    if (!campus || !filters.room_capacity) return;
    const allowed = campusCapacities(campus).map(String);
    if (!allowed.includes(String(filters.room_capacity))) {
      setFilters((prev) => ({ ...prev, room_capacity: "" }));
    }
  }, [campus, filters.room_capacity]);

  // ===== Переход из общей ленты на конкретную анкету =====

  // Пришли по ссылке — сначала выясняем, чья это анкета: от неё зависит и
  // кампус-отель, и лента, в которой её вообще видно.
  useEffect(() => {
    if (!targetId || loadingMe || !identityAvailable) return;
    let cancelled = false;

    fetchProfile(targetId)
      .then((target) => {
        if (cancelled) return;
        // Свой пол берём из анкеты, а без анкеты — из выбора на входе.
        const myGender = myProfile?.gender || gender;
        if (myGender && target.gender !== myGender) {
          setTargetError(
            `Эта анкета из ленты ${GENDER_OF[target.gender] || "другого пола"}` +
              " — открыть её нельзя. Соседей подбирают только внутри своего пола."
          );
          return;
        }
        setTargetError("");
        // Ленту переключаем на анкету: иначе ссылка приводит в пустоту, если
        // человек до этого смотрел другой отель.
        if (target.campus !== campus) chooseCampus(target.campus);
        if (!gender) chooseGender(target.gender);

        setLinkedProfile(target);
      })
      .catch(() => {
        if (!cancelled) setTargetError("Анкета сейчас недоступна.");
      });

    return () => {
      cancelled = true;
    };
    // Достаточно одного захода: как только стало известно, кто я, решение
    // принято и повторять его не нужно.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetId, loadingMe, identityAvailable]);

  useEffect(() => {
    if (tab !== "groups" || roomTarget === null || roomFeed.loading || !roomFeed.loaded) return;
    const node = document.getElementById(`room-${roomTarget}`);
    if (node) {
      node.scrollIntoView({ block: "start" });
      node.focus({ preventScroll: true });
    } else {
      setError("Эта комната больше недоступна.");
    }
    setRoomTarget(null);
  }, [tab, roomTarget, roomFeed.loading, roomFeed.loaded, groups]);

  function switchFeed(nextTab) {
    if (tab === nextTab) return;
    setRoomTarget(null);
    setError("");
    setTab(nextTab);
    window.scrollTo(0, 0);
  }

  function openRoom(id) {
    setError("");
    setRoomTarget(id);
    setTab("groups");
    void roomFeed.reload();
  }

  function handleCreated(profile) {
    setModal(null);
    setFilters(EMPTY_FILTERS);
    setMatchingOnly(false);
    remember(profile); // запоминаем как «мою анкету»
    setProfiles((prev) => [profile, ...prev]);
  }

  function handleUpdated(profile) {
    setModal(null);
    remember(profile); // обновляем «мою анкету»
    // Поправил пол в анкете — значит, на входе ошибся лентой. Переключаем её
    // следом, иначе человек остался бы смотреть чужую половину сервиса.
    if (profile.gender !== gender) {
      chooseGender(profile.gender);
      return; // ленту перезапросит эффект на смену пола
    }
    if (profile.campus === campus) {
      void peopleFeed.reload();
      if (profile.group_id) void roomFeed.reload();
    }
  }

  async function handleDeleted() {
    setModal(null);
    forget();
    setMatchingOnly(false);
    await refresh(null);
  }

  useEffect(() => {
    loadRequests(myProfile);
  }, [myProfile]);

  async function refresh(profileFallback = myProfile) {
    const updates = { singles: peopleFeed.reload(), groups: roomFeed.reload() };
    const me = await reloadMe();
    await Promise.all([updates[tab], loadRequests(me || profileFallback)]);
  }

  async function withBusy(action) {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true); setError("");
    try {
      await action();
      await refresh();
      return true;
    } catch (err) {
      setError(err.message);
      if (err.status === 409) await refresh();
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  const handleRequest = (groupId) =>
    withBusy(() => requestJoin(groupId, myProfile.id));

  const handleCancelRequest = (requestId) =>
    withBusy(() => cancelRequest(requestId, myProfile.id));

  const handleVote = (requestId, approve) =>
    withBusy(() => voteRequest(requestId, myProfile.id, approve));

  const handleLeave = (groupId) =>
    withBusy(() => leaveGroup(groupId, myProfile.id));

  const handleCreateGroup = (capacity) =>
    withBusy(() => createGroup(capacity, myProfile.id));

  // Комнату можно сузить и расширить: собрались на 4, а набралось двое.
  const handleChangeCapacity = (groupId, capacity) =>
    withBusy(() => changeGroupCapacity(groupId, myProfile.id, capacity));

  // Позвать жить вместе: комната появится только когда человек согласится.
  const handleInvite = (toProfileId, capacity) =>
    withBusy(() => createInvite(myProfile.id, toProfileId, capacity));

  const handleRespondInvite = (inviteId, accept) =>
    withBusy(() => respondInvite(inviteId, myProfile.id, accept));

  // Модерация: убрать лишнюю анкету прямо из ленты. Кнопку видит только админ,
  // и право на это всё равно проверяет сервер по подписи Telegram.
  const handleAdminDelete = (profileId) =>
    withBusy(() => adminDeleteProfile(profileId));

  if (!isInsideTelegram() && !access?.development_mode) {
    return <AccessGate config={access} failed={accessFailed} profileId={targetId}/>;
  }

  // Кампус-отель определяет и ленту, и размеры комнат — спрашиваем его первым.
  if (!campus) {
    return <CampusGate onSelect={chooseCampus} />;
  }

  if (!gender) {
    return <GenderGate campus={campus} onBack={() => myProfile?.gender ? chooseGender(myProfile.gender) : resetCampus()} onSelect={chooseGender} />;
  }

  // Приглашения ко мне — их надо показать в самом приложении: бот доходит
  // только до тех, кто нажимал /start.
  const incomingInvites = myInvites.filter(
    (i) => i.to_profile_id === myProfile?.id
  );
  const openGroups = groups.filter((g) => g.spots_left > 0);
  // Собранная комната ничего не предлагает: заявку в неё не подать, а места
  // в ленте она занимала столько же, сколько живая. Такие комнаты уезжают
  // вниз и сворачиваются в строку. Своя комната и та, куда отправлена
  // заявка, остаются наверху развёрнутыми — за ними в ленту и возвращаются.
  const pinnedGroupIds = new Set([
    ...(myProfile?.group_id ? [myProfile.group_id] : []),
    ...myRequests.map((r) => r.group_id),
  ]);
  const liveGroups = groups.filter(
    (g) => g.spots_left > 0 || pinnedGroupIds.has(g.id)
  );
  const doneGroups = groups.filter(
    (g) => g.spots_left <= 0 && !pinnedGroupIds.has(g.id)
  );
  const canStartGroup = myProfile && !myProfile.group_id;
  const capacities = campusCapacities(campus);
  const profileDetailsProps = {
    myProfile,
    capacities,
    onOpenRoom: openRoom,
    actionError,
    onInvite: handleInvite,
    canModerate: isAdmin,
    onAdminDelete: handleAdminDelete,
    busy,
  };
  const inviteForProfile = (profileId) => myInvites.find(
    (invite) => invite.to_profile_id === profileId && invite.from_profile_id === myProfile?.id
  );
  const filtersActive = Object.values(filters).some(value => value !== "") || matchingOnly;
  const profileOpen = modal === "create" || modal === "edit";
  const profileAction = () => setModal(myProfile ? "edit" : "create");

  return (
    <div className={`app neighbor-app neighbor-app--${campus}`}>
      <header className="header">
        <div className="header__inner">
          <div className="header__brand"><Brand /><span className="header__subject">Соседи <small>{CAMPUS[campus]}</small></span></div>

          <div className="header__right">
            <ThemeToggle compact />
            <FeedSettings>
            {/* Пока анкеты нет, отель можно перевыбрать здесь. С анкетой
                она хранится в ней — и меняется только там, чтобы случайное
                нажатие не выкинуло человека из комнаты. */}
            {myProfile ? (
              <span
                className="header__campus"
                title="Сменить кампус-отель можно в анкете"
              >
                {CAMPUS[campus]}
              </span>
            ) : (
              <button
                className="header__gender"
                onClick={resetCampus}
                title="Сменить"
              >
                {CAMPUS[campus]}
                <span className="header__gender-change">сменить</span>
              </button>
            )}
            <button
              className="header__gender"
              onClick={() => setGender("")}
              title="Сменить"
            >
              {GENDER_WORD[gender]}
              <span className="header__gender-change">сменить</span>
            </button>
            {isAdmin && (
              <button
                className="header__admin"
                onClick={() => setModal("admin")}
                title="Выгрузка данных"
              >
                <span className="header__admin-full">Админка</span>
                <span className="header__admin-icon" aria-hidden="true">
                  ⚙
                </span>
              </button>
            )}
            </FeedSettings>
            {myProfile ? (
              <button
                className="header__cta"
                onClick={profileAction}
              >
                <span className="header__cta-full">Моя анкета</span>
                <span className="header__cta-short">Анкета</span>
                <span className="header__cta-icon" aria-hidden="true">✎</span>
              </button>
            ) : (
              <button
                className="header__cta"
                onClick={profileAction}
              >
                <span className="header__cta-full">Разместить анкету</span>
                <span className="header__cta-short">+ Анкета</span>
                <span className="header__cta-icon" aria-hidden="true">+</span>
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="container">
        {tab === "singles" ? (
          <div className="neighbors-hero">
            <span className="neighbors-hero__graphic" aria-hidden="true" />
            <p className="neighbors-hero__label"><span aria-hidden="true" />Кампус-отель</p>
            <h1>Соседи<br /><em>{campus === "disk" ? "в Диске" : "в Облаке"}</em></h1>
          </div>
        ) : <h1 className="neighbors-heading">Комнаты</h1>}

        {/* Без анкеты человека не видно и он не может ничего сделать, а кнопку
            в шапке замечали не с первого раза — зовём крупно и по делу. */}
        {!loadingMe && !myProfile && (
          <div className="promo">
            <div className="promo__text">
              <strong className="promo__title">Давай найдём твоих соседей</strong>
              <span className="promo__sub">
                Расскажи немного о себе: будущим соседям будет проще
                познакомиться и собрать комнату вместе.
              </span>
            </div>
            <button className="promo__btn" onClick={profileAction}>
              Разместить анкету
            </button>
          </div>
        )}

        <nav className="neighbors-nav" aria-label="Разделы приложения">
          <button type="button" aria-current={tab === "singles" && !profileOpen ? "page" : undefined} onClick={() => switchFeed("singles")}>
            <span className="neighbors-nav__icon neighbors-nav__icon--people" aria-hidden="true" />Люди
          </button>
          <button type="button" aria-current={tab === "groups" && !profileOpen ? "page" : undefined} onClick={() => switchFeed("groups")}>
            <span className="neighbors-nav__icon neighbors-nav__icon--rooms" aria-hidden="true" />Комнаты
          </button>
          <button type="button" className="neighbors-nav__profile" aria-current={profileOpen ? "page" : undefined} onClick={profileAction} disabled={loadingMe}>
            <span className="neighbors-nav__icon neighbors-nav__icon--profile" aria-hidden="true" />Анкета
          </button>
        </nav>

        {/* Пришли по ссылке из общей ленты, но показать анкету не вышло —
            объясняем почему, иначе ссылка выглядит просто сломанной. */}
        {targetError && (
          <div className="notice">
            <span className="notice__text">{targetError}</span>
            <button
              className="notice__close"
              onClick={() => setTargetError("")}
              aria-label="Скрыть"
            >
              ×
            </button>
          </div>
        )}

        {incomingInvites.length > 0 && (
          <div className="invites">
            {incomingInvites.map((inv) => (
              <div className="invite" key={inv.id}>
                <span className="invite__text">
                  🤝 <strong>{inv.from_profile.name}</strong> зовёт жить вместе —
                  комната на {inv.capacity}
                </span>
                <div className="invite__actions">
                  <button
                    className="invite__yes"
                    onClick={() => handleRespondInvite(inv.id, true)}
                    disabled={busy}
                  >
                    Согласиться
                  </button>
                  <button
                    className="invite__no"
                    onClick={() => handleRespondInvite(inv.id, false)}
                    disabled={busy}
                  >
                    Отказаться
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === "singles" && (
          <Filters
            filters={filters}
            campus={campus}
            onChange={setFilters}
            onReset={() => {
              setFilters(EMPTY_FILTERS);
              setMatchingOnly(false);
            }}
            idealCount={fullMatches.length}
            idealOn={matchingOnly}
            onToggleIdeal={() => setMatchingOnly(value => !value)}
          />
        )}

        {(loading || activeFeed.loading) && <p className="feed-status" role="status">{loading ? "Загружаем анкеты и комнаты…" : "Обновляем подборку…"}</p>}
        {loading && <div className="feed-skeleton" aria-hidden="true">{[1,2,3].map(n => <div key={n}><span /><i /><i /></div>)}</div>}
        {error && <div className="feed-error" role="alert"><p>{error}</p>{activeFeed.errorStatus === 401 && access?.telegram_app_url ? <a className="access-gate__button" href={access.telegram_app_url}>Открыть приложение заново →</a> : <button type="button" onClick={() => { setError(""); activeFeed.reload(); }}>Попробовать ещё раз</button>}</div>}

        {!loading && (!error || activeFeed.loaded) && tab === "singles" && (
          <>
            <p className="count neighbors-result-count">Анкет в подборке: <strong>{shownProfiles.length}</strong></p>
            {shownProfiles.length === 0 ? (
              <p className="state">
                {filtersActive
                  ? "Под фильтры никто не подошёл. Попробуй смягчить условия."
                  : "Пока здесь пусто. Размести анкету первым — и тебя увидят."}
              </p>
            ) : (
              <div className="grid grid--neighbors">
                {shownProfiles.slice(0, visibleCount).map((p) => (
                  <RoommateCard
                    {...profileDetailsProps}
                    key={p.id}
                    profile={p}
                    match={matches.get(p.id)}
                    invite={inviteForProfile(p.id)}
                  />
                ))}
              </div>
            )}
            {shownProfiles.length > visibleCount && <div className="feed-more"><p>Показано {Math.min(visibleCount, shownProfiles.length)} из {shownProfiles.length}</p><button type="button" onClick={() => setVisibleCount(count => count + 24)}>Показать ещё 24</button></div>}
          </>
        )}

        {!loading && (!error || activeFeed.loaded) && tab === "groups" && (
          <>
            <div className="groups__top">
              {/* Сколько всего комнат, показывает вкладка. Здесь — только про
                  места, и когда числа совпали бы, говорим словами. */}
              {groups.length > 0 && (
                <p className="count">
                  {openGroups.length === 0 ? (
                    "Все комнаты уже собраны"
                  ) : openGroups.length === groups.length ? (
                    "Места есть во всех комнатах"
                  ) : (
                    <>
                      Комнат с местами: <strong>{openGroups.length}</strong>
                    </>
                  )}
                </p>
              )}
              {canStartGroup && (
                <div className="groups__new">
                  <span>Договорились с кем-то? Создай комнату:</span>
                  {capacities.map((capacity) => (
                    <button
                      key={capacity}
                      className="groups__new-btn"
                      onClick={() => handleCreateGroup(capacity)}
                      disabled={busy}
                    >
                      на {capacity}
                    </button>
                  ))}
                </div>
              )}
              {!myProfile && (
                <p className="groups__hint">
                  Размести анкету — и сможешь собрать свою комнату или вступить
                  в чужую.
                </p>
              )}
            </div>

            {groups.length === 0 ? (
              <p className="state">
                Пока никто не собрался. Собери первую комнату — остальные
                присоединятся.
              </p>
            ) : (
              <>
                {liveGroups.length > 0 && (
                  <div className="grid grid--groups">
                    {liveGroups.map((g) => (
                      <GroupCard
                        key={g.id}
                        group={g}
                        myProfile={myProfile}
                        requests={incoming.filter((r) => r.group_id === g.id)}
                        myRequestHere={myRequests.find(
                          (r) => r.group_id === g.id
                        )}
                        onRequest={handleRequest}
                        onCancelRequest={handleCancelRequest}
                        onVote={handleVote}
                        onLeave={handleLeave}
                        onChangeCapacity={handleChangeCapacity}
                        capacities={capacities}
                        busy={busy}
                      />
                    ))}
                  </div>
                )}

                {doneGroups.length > 0 && (
                  <section className="groups__done">
                    <h3 className="groups__done-title">
                      Собранные комнаты
                      <span className="groups__done-count">
                        {doneGroups.length}
                      </span>
                    </h3>
                    <div className="groups__done-list">
                      {doneGroups.map((g) => (
                        <GroupCard
                          key={g.id}
                          group={g}
                          myProfile={myProfile}
                          requests={incoming.filter((r) => r.group_id === g.id)}
                          myRequestHere={myRequests.find(
                            (r) => r.group_id === g.id
                          )}
                          onRequest={handleRequest}
                          onCancelRequest={handleCancelRequest}
                          onVote={handleVote}
                          onLeave={handleLeave}
                          onChangeCapacity={handleChangeCapacity}
                          capacities={capacities}
                          busy={busy}
                          collapsible
                        />
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}
          </>
        )}
      </main>

      <footer className="footer">
        <span>Кампус-отели Диск и Облако · сервис поиска соседей по комнате</span>
        <a className="footer__projects" href="https://cu.vubni.ru/" target="_blank" rel="noopener noreferrer">Все проекты · Рядом ↗</a>
      </footer>

      {linkedProfile && (
        <ProfileDetails
          {...profileDetailsProps}
          profile={profiles.find((profile) => profile.id === linkedProfile.id) ?? linkedProfile}
          match={compareHabits(myProfile, linkedProfile)}
          invite={inviteForProfile(linkedProfile.id)}
          onClose={() => setLinkedProfile(null)}
        />
      )}

      {modal === "admin" && (
        <AdminPanel onClose={() => setModal(null)} onChanged={refresh} />
      )}

      {(modal === "create" || modal === "edit") && (
        <AddProfileModal
          gender={gender}
          campus={campus}
          profile={modal === "edit" ? myProfile : null}
          onClose={() => setModal(null)}
          onCreated={handleCreated}
          onUpdated={handleUpdated}
          onDeleted={handleDeleted}
        />
      )}
    </div>
  );
}
