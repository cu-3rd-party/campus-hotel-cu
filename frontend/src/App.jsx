import { useEffect, useRef, useState } from "react";
import {
  adminDeleteProfile,
  cancelBlockRequest,
  cancelRequest,
  changeGroupCapacity,
  createGroup,
  createInvite,
  fetchBlockCandidates,
  fetchBlockRequests,
  fetchBlocks,
  fetchConfig,
  fetchGroupRequests,
  fetchGroups,
  fetchIdealProfiles,
  fetchMyInvites,
  fetchMyRequests,
  fetchProfile,
  respondInvite,
  fetchProfiles,
  leaveBlock,
  leaveGroup,
  requestBlock,
  requestJoin,
  voteBlockRequest,
  voteRequest,
} from "./api.js";
import RoommateCard from "./components/RoommateCard.jsx";
import GroupCard from "./components/GroupCard.jsx";
import BlockPanel from "./components/BlockPanel.jsx";
import Filters from "./components/Filters.jsx";
import AddProfileModal from "./components/AddProfileModal.jsx";
import AdminPanel from "./components/AdminPanel.jsx";
import GenderGate from "./components/GenderGate.jsx";
import CampusGate from "./components/CampusGate.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";
import {
  CAMPUS,
  campusCapacities,
  campusHasBlocks,
  campusRoomsText,
} from "./labels.js";
import { getStartParam, initWebApp } from "./telegram.js";
import { releaseStuckLock } from "./useModalLock.js";
import { useMyProfile } from "./useMyProfile.js";
import { useDebouncedValue, useRemoteList } from "./useRemoteList.js";
import { LatestRequest } from "./request.mjs";
import { readStored, writeStored, removeStored } from "./storage.mjs";
import FeedSettings from "./components/FeedSettings.jsx";
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
  const [tab, setTab] = useState("singles"); // "singles" | "groups" | "blocks"

  // Собранные блоки: две комнаты по 6 человек вместе. Только в «Диске».
  // Что доступно моей комнате по блокам: с кем можно объединиться и кто уже
  // позвал. Грузим отдельно — это внутреннее дело комнаты, а не общая лента.
  const [blockCandidates, setBlockCandidates] = useState([]);
  const [blockRequests, setBlockRequests] = useState([]);
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

  // «Идеальные соседи»: у кого совпали все мои параметры. Подбирает сервер.
  const [idealIds, setIdealIds] = useState([]);
  const [idealOn, setIdealOn] = useState(false);

  // Анкета из ссылки в общей ленте: на неё надо прокрутить и подсветить её.
  // Читаем один раз при запуске — дальше это уже история, а не команда.
  const [targetId] = useState(startProfileId);
  const [targetError, setTargetError] = useState("");
  const [highlightId, setHighlightId] = useState(null);
  // Прокручиваем ровно один раз: иначе любое обновление ленты дёргало бы
  // человека обратно к чужой анкете.
  const scrolledTo = useRef(null);

  const { myProfile, loadingMe, remember, forget, reloadMe } = useMyProfile();
  const searchFilters = useDebouncedValue(filters);
  const scope = `${gender}:${campus}`;
  const enabled = Boolean(gender && campus);
  const peopleFeed = useRemoteList(JSON.stringify(searchFilters), scope,
    signal => fetchProfiles({ ...searchFilters, gender, campus, without_group: true }, { signal }), enabled);
  const roomFeed = useRemoteList(scope, scope,
    signal => fetchGroups({ gender, campus }, { signal }), enabled);
  const blockFeed = useRemoteList(scope, scope,
    signal => fetchBlocks({ gender, campus }, { signal }), enabled && campusHasBlocks(campus));
  const profiles = peopleFeed.data, groups = roomFeed.data, blocks = blockFeed.data;
  const setProfiles = peopleFeed.setData;
  const activeFeed = tab === "groups" ? roomFeed : tab === "blocks" ? blockFeed : peopleFeed;
  const loading = activeFeed.loading && !activeFeed.loaded;
  const error = actionError || activeFeed.error;
  const [visibleCount, setVisibleCount] = useState(24);
  const idealRequest = useRef(new LatestRequest());
  const inboxVersion = useRef(0);
  const busyRef = useRef(false);
  useEffect(() => { setVisibleCount(24); }, [scope, searchFilters, idealOn]);
  useEffect(() => () => idealRequest.current.cancel(), []);

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

  /**
   * Идеальные соседи — отдельно от ленты, и это принципиально.
   *
   * Их сервер подбирает по моей анкете, перебирая все анкеты кампуса, и запрос
   * бывает заметно медленнее остальных. Пока он стоял в одном Promise.all с
   * лентой, лента ждала его — человек всё это время видел «Загрузка…» на весь
   * экран, которую нечем листать. Подсказка не стоит того, чтобы задерживать
   * главное: приходит — показываем кнопку, не приходит — просто живём без неё.
   */
  async function loadIdeal(myId) {
    if (!myId) { idealRequest.current.cancel(); setIdealIds([]); return; }
    return idealRequest.current.run(
      signal => fetchIdealProfiles(myId, { signal }),
      ideal => setIdealIds(ideal.map(profile => profile.id)),
      () => setIdealIds([]),
    );
  }

  /** Заявки грузим только там, где они нужны: в свою комнату и свои исходящие. */
  async function loadRequests(me) {
    const version = ++inboxVersion.current;
    if (!me) {
      setIncoming([]);
      setMyRequests([]);
      setMyInvites([]);
      setBlockRequests([]);
      setBlockCandidates([]);
      return;
    }
    // Блоки касаются только тех, кто уже собрал комнату в отеле с блоками.
    const withBlocks = Boolean(me.group_id) && campusHasBlocks(me.campus);
    try {
      const results = await Promise.allSettled([
        fetchMyRequests(me.id),
        me.group_id ? fetchGroupRequests(me.group_id) : Promise.resolve([]),
        fetchMyInvites(me.id),
        withBlocks ? fetchBlockRequests(me.group_id) : Promise.resolve([]),
        withBlocks ? fetchBlockCandidates(me.group_id) : Promise.resolve([]),
      ]);
      if (version !== inboxVersion.current) return;
      const [mine, inbox, invites, blockReqs, cands] = results.map(result => result.status === "fulfilled" ? result.value : []);
      setMyRequests(mine);
      setIncoming(inbox);
      setMyInvites(invites);
      setBlockRequests(blockReqs);
      setBlockCandidates(cands);
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
      .then((cfg) => setIsAdmin(Boolean(cfg.is_admin)))
      .catch(() => setIsAdmin(false));
  }, []);

  // Each feed loads independently through useRemoteList; typing only requests people.

  // А вот подсказка про идеальных соседей без анкеты бессмысленна — её и
  // грузим тогда, когда стало известно, кто я. Отдельным запросом, поэтому
  // ленту это уже не задерживает и дважды её не дёргает.
  useEffect(() => {
    if (loadingMe) return;
    loadIdeal(myProfile?.id);
  }, [loadingMe, myProfile?.id]);

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
    if (!targetId || loadingMe) return;
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

        // В ленте «ищут соседей» только те, кто ещё не в комнате. Если человек
        // уже собрался — искать его карточку там бесполезно, честнее сказать.
        if (target.group_id) {
          setTargetError(
            `${target.name} уже собрал(а) комнату — загляни во вкладку «Комнаты».`
          );
          setTab("groups");
          return;
        }
        setTab("singles");
        setHighlightId(target.id);
      })
      .catch(() => {
        if (!cancelled) setTargetError("Анкету не нашли — её могли удалить.");
      });

    return () => {
      cancelled = true;
    };
    // Достаточно одного захода: как только стало известно, кто я, решение
    // принято и повторять его не нужно.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetId, loadingMe]);

  useEffect(() => {
    const index = profiles.findIndex(profile => profile.id === highlightId);
    if (index >= visibleCount) setVisibleCount(Math.ceil((index + 1) / 24) * 24);
  }, [highlightId, profiles, visibleCount]);

  // Анкета доехала до ленты — прокручиваем к ней и снимаем подсветку.
  useEffect(() => {
    if (!highlightId || loading) return;
    if (scrolledTo.current === highlightId) return;
    const node = document.getElementById(`profile-${highlightId}`);
    if (!node) return;
    scrolledTo.current = highlightId;
    // Считаем позицию сами и прокручиваем двухаргументным scrollTo. Так же,
    // как в useModalLock, обходим { behavior: "instant" }: в Safari оно
    // появилось только к 15.4, а собираемся мы под Safari 14.
    // Прокрутка нужна именно мгновенная: плавную браузер не проигрывает, пока
    // вкладка не на виду, — а мини-апп по ссылке как раз стартует в фоне, и
    // человек оказывался в начале ленты.
    const rect = node.getBoundingClientRect();
    const center = rect.top + window.scrollY - (window.innerHeight - rect.height) / 2;
    window.scrollTo(0, Math.max(0, center));
    // Подсветка — подсказка «вот она», а не постоянное состояние карточки.
    const id = setTimeout(() => setHighlightId(null), 2600);
    return () => clearTimeout(id);
  }, [highlightId, loading, profiles, visibleCount]);

  function handleCreated(profile) {
    setModal(null);
    setFilters(EMPTY_FILTERS);
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
    // Если анкета в ленте (без комнаты) — освежаем её на месте.
    setProfiles((prev) => prev.map((p) => (p.id === profile.id ? profile : p)));
  }

  async function handleDeleted() {
    setModal(null);
    forget();
    await refresh();
  }

  useEffect(() => {
    loadRequests(myProfile);
  }, [myProfile]);

  async function refresh() {
    const updates = { singles: peopleFeed.reload(), groups: roomFeed.reload(), blocks: blockFeed.reload() };
    const me = await reloadMe();
    void loadRequests(me || myProfile);
    void loadIdeal((me || myProfile)?.id);
    // Keep secondary refreshes in the background; the active tab remains usable.
    await updates[tab];
  }

  async function withBusy(action) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setError("");
    try { await action(); await refresh(); }
    catch (err) { setError(err.message); }
    finally { busyRef.current = false; setBusy(false); }
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

  // Блоки: объединяются комнатами, поэтому решает не один человек — согласие
  // должны дать все жильцы позванной комнаты.
  const handleRequestBlock = (toGroupId) =>
    withBusy(() => requestBlock(myProfile.id, toGroupId));

  const handleVoteBlock = (requestId, approve) =>
    withBusy(() => voteBlockRequest(requestId, myProfile.id, approve));

  const handleCancelBlock = (requestId) =>
    withBusy(() => cancelBlockRequest(requestId, myProfile.id));

  const handleLeaveBlock = (blockId) =>
    withBusy(() => leaveBlock(blockId, myProfile.id));

  // Модерация: убрать лишнюю анкету прямо из ленты. Кнопку видит только админ,
  // и право на это всё равно проверяет сервер по подписи Telegram.
  const handleAdminDelete = (profileId) =>
    withBusy(() => adminDeleteProfile(profileId));

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
  const hasBlocks = campusHasBlocks(campus);
  // Моя комната и мой блок — из уже загруженных лент, отдельный запрос не нужен.
  const myGroup = myProfile?.group_id
    ? groups.find((g) => g.id === myProfile.group_id)
    : null;
  const myBlock = myGroup?.block_id
    ? blocks.find((b) => b.id === myGroup.block_id)
    : null;
  // Входящие предложения о блоке зовут не хуже приглашений — показываем счётчик.
  const blockInbox = myGroup
    ? blockRequests.filter((r) => r.to_group_id === myGroup.id).length
    : 0;
  // Пусто из-за фильтров или тут вообще никого нет — это разные сообщения.
  const filtersActive = Object.values(filters).some((v) => v !== "") || idealOn;
  // «Идеальные» пересекаем с лентой, а не заменяем её: обычные фильтры при
  // этом продолжают работать.
  const idealSet = new Set(idealIds);
  const shownProfiles = idealOn
    ? profiles.filter((p) => idealSet.has(p.id))
    : profiles;

  return (
    <div className="app">
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
                onClick={() => setModal("edit")}
              >
                <span className="header__cta-full">Моя анкета</span>
                <span className="header__cta-short">Анкета</span>
                <span className="header__cta-icon" aria-hidden="true">✎</span>
              </button>
            ) : (
              <button
                className="header__cta"
                onClick={() => setModal("create")}
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
        <div className="hero">
          <h1 className="hero__title">
            Соседи, с которыми <span className="accent">по пути</span>
          </h1>
          <p className="hero__sub">
            Кампус-отель «{CAMPUS[campus]}» · комнаты на{" "}
            {campusRoomsText(campus)} человека · только{" "}
            {GENDER_WORD[gender].toLowerCase()}
          </p>
        </div>

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
            <button className="promo__btn" onClick={() => setModal("create")}>
              Разместить анкету
            </button>
          </div>
        )}

        <div className="tabs">
          <button
            aria-pressed={tab === "singles"}
            className={`tabs__btn${tab === "singles" ? " tabs__btn--on" : ""}`}
            onClick={() => setTab("singles")}
          >
            Ищут соседей
            <span className="tabs__badge">{profiles.length}</span>
          </button>
          <button
            aria-pressed={tab === "groups"}
            className={`tabs__btn${tab === "groups" ? " tabs__btn--on" : ""}`}
            onClick={() => setTab("groups")}
          >
            Комнаты
            <span className="tabs__badge">{groups.length}</span>
          </button>
          {/* Блоки бывают только в «Диске» — в «Облаке» вкладку не показываем. */}
          {hasBlocks && (
            <button
              className={`tabs__btn${tab === "blocks" ? " tabs__btn--on" : ""}`}
              onClick={() => setTab("blocks")}
            >
              Блок
              {blockInbox > 0 && (
                <span className="tabs__badge tabs__badge--alert">
                  {blockInbox}
                </span>
              )}
            </button>
          )}
        </div>

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
              setIdealOn(false);
            }}
            idealCount={idealIds.length}
            idealOn={idealOn}
            onToggleIdeal={() => setIdealOn((v) => !v)}
          />
        )}

        {activeFeed.loading && <p className="feed-status" role="status">{loading ? "Загружаем анкеты и комнаты…" : "Обновляем подборку…"}</p>}
        {loading && <div className="feed-skeleton" aria-hidden="true">{[1,2,3].map(n => <div key={n}><span /><i /><i /></div>)}</div>}
        {error && <div className="feed-error" role="alert"><p>{error}</p><button type="button" onClick={() => { setError(""); activeFeed.reload(); }}>Попробовать ещё раз</button></div>}

        {!loading && (!error || activeFeed.loaded) && tab === "singles" && (
          <>
            {/* Сколько анкет в ленте, написано на вкладке, а сколько из них
                идеально подходят — на самой кнопке «идеального соседа».
                Строкой ниже остаётся только то, чего нигде больше нет. */}
            {openGroups.length > 0 && (
              <p className="count">
                Комнат с местами: <strong>{openGroups.length}</strong>
              </p>
            )}
            {shownProfiles.length === 0 ? (
              <p className="state">
                {filtersActive
                  ? "Под фильтры никто не подошёл. Попробуй смягчить условия."
                  : "Пока здесь пусто. Размести анкету первым — и тебя увидят."}
              </p>
            ) : (
              <div className="grid">
                {shownProfiles.slice(0, visibleCount).map((p) => (
                  <RoommateCard
                    key={p.id}
                    profile={p}
                    myProfile={myProfile}
                    capacities={capacities}
                    // Пришли по ссылке из общей ленты — подсвечиваем ту анкету,
                    // за которой человек сюда и шёл.
                    highlight={p.id === highlightId}
                    ideal={idealSet.has(p.id)}
                    invite={myInvites.find(
                      (i) =>
                        i.to_profile_id === p.id &&
                        i.from_profile_id === myProfile?.id
                    )}
                    onInvite={handleInvite}
                    canModerate={isAdmin}
                    onAdminDelete={handleAdminDelete}
                    busy={busy}
                  />
                ))}
              </div>
            )}
            {shownProfiles.length > visibleCount && <div className="feed-more"><p>Показано {Math.min(visibleCount, shownProfiles.length)} из {shownProfiles.length}</p><button type="button" onClick={() => setVisibleCount(count => count + 24)}>Показать ещё 24</button></div>}
          </>
        )}

        {!loading && (!error || activeFeed.loaded) && tab === "blocks" && (
          <BlockPanel
            campus={campus}
            myProfile={myProfile}
            myGroup={myGroup}
            myBlock={myBlock}
            candidates={blockCandidates}
            requests={blockRequests}
            onRequestBlock={handleRequestBlock}
            onVoteBlock={handleVoteBlock}
            onCancelBlock={handleCancelBlock}
            onLeaveBlock={handleLeaveBlock}
            busy={busy}
          />
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
