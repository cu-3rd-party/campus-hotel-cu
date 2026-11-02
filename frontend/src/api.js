import { requestJSON } from "./request.mjs";
import { getInitData } from "./telegram.js";

const BASE = "/api";

/**
 * Подпись Telegram в каждом запросе.
 *
 * Это и есть авторизация: initData подписан токеном бота, подделать его
 * нельзя, и сервер по нему понимает, кто именно действует. Пусто (обычный
 * браузер) — сервер ответит 401, если у него настроен токен бота.
 */
function authHeaders(extra = {}) {
  const initData = getInitData();
  return initData ? { ...extra, "X-Telegram-Init-Data": initData } : { ...extra };
}

const JSON_HEADERS = () => authHeaders({ "Content-Type": "application/json" });


function query(filters) {
  return new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== "" && value !== null && value !== undefined)).toString();
}
const read = (path, fallback, options = {}) => requestJSON(`${BASE}${path}`, fallback, { ...options, headers: authHeaders(options.headers) });

export function fetchProfiles(filters = {}, options = {}) {
  return read(`/profiles?${query(filters)}`, "Не удалось загрузить анкеты", options);
}
export function fetchIdealProfiles(profileId, options = {}) {
  return read(`/profiles/ideal${profileId ? `?profile_id=${profileId}` : ""}`, "Не удалось подобрать соседей", options);
}
export function fetchGroups(filters = {}, options = {}) {
  return read(`/groups?${query(filters)}`, "Не удалось загрузить комнаты", options);
}

export async function createGroup(capacity, profileId) {
  return requestJSON(`${BASE}/groups`, "Не удалось создать комнату", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ capacity, profile_id: profileId }),
  });
}

// Вступить напрямую нельзя — только подать заявку, её подтверждают жильцы.
export async function requestJoin(groupId, profileId) {
  return requestJSON(`${BASE}/groups/${groupId}/requests`, "Не удалось отправить заявку", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId }),
  });
}

export async function fetchGroupRequests(groupId) {
  return read(`/groups/${groupId}/requests?status=pending`, "Не удалось загрузить заявки");
}

export async function fetchMyRequests(profileId) {
  return read(`/profiles/${profileId}/requests?status=pending`, "Не удалось загрузить заявки");
}

export async function voteRequest(requestId, profileId, approve) {
  return requestJSON(`${BASE}/requests/${requestId}/vote`, "Не удалось проголосовать", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId, approve }),
  });
}

export async function cancelRequest(requestId, profileId) {
  return requestJSON(`${BASE}/requests/${requestId}/cancel`, "Не удалось отменить заявку", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId }),
  });
}

/**
 * Сузить или расширить уже созданную комнату.
 * Меняет любой жилец; меньше числа участников сервер не даст.
 */
export async function changeGroupCapacity(groupId, profileId, capacity) {
  return requestJSON(`${BASE}/groups/${groupId}/capacity`, "Не удалось изменить размер комнаты", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId, capacity }),
  });
}

export async function leaveGroup(groupId, profileId) {
  return requestJSON(`${BASE}/groups/${groupId}/leave`, "Не удалось выйти из комнаты", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId }),
  });
}

// ===== Блоки: две комнаты по 6 человек вместе (2+4 или 3+3) =====

export function fetchBlocks(filters = {}, options = {}) {
  return read(`/blocks?${query(filters)}`, "Не удалось загрузить блоки", options);
}

/** Комнаты, с которыми моя соберёт полный блок — подбирает сервер по размеру. */
export async function fetchBlockCandidates(groupId) {
  return read(`/groups/${groupId}/block-candidates`, "Не удалось загрузить комнаты для блока");
}

/** Заявки на блок моей комнаты — и входящие, и исходящие. */
export async function fetchBlockRequests(groupId) {
  return read(`/groups/${groupId}/block-requests?status=pending`, "Не удалось загрузить заявки на блок");
}

export async function requestBlock(profileId, toGroupId) {
  return requestJSON(`${BASE}/blocks/requests`, "Не удалось позвать комнату в блок", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId, to_group_id: toGroupId }),
  });
}

export async function voteBlockRequest(requestId, profileId, approve) {
  return requestJSON(`${BASE}/blocks/requests/${requestId}/vote`, "Не удалось ответить на предложение", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId, approve }),
  });
}

export async function cancelBlockRequest(requestId, profileId) {
  return requestJSON(`${BASE}/blocks/requests/${requestId}/cancel`, "Не удалось отменить предложение", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId }),
  });
}

export async function leaveBlock(blockId, profileId) {
  return requestJSON(`${BASE}/blocks/${blockId}/leave`, "Не удалось выйти из блока", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId }),
  });
}

/**
 * Аватарки из профиля Telegram — порциями, чтобы форма открывалась быстро.
 * Возвращает { photos, total }: по total видно, есть ли что догружать.
 */
export async function fetchTelegramPhotos(initData, offset = 0, limit = 6) {
  return requestJSON(`${BASE}/telegram/photos`, "Не удалось получить аватарки из Telegram", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ init_data: initData, offset, limit }),
  });
}

/** Найти свою анкету по подписи Telegram — не полагаясь на localStorage. */
export async function fetchMyProfileByTelegram(initData) {
  return read("/profiles/me", "Не удалось открыть свою анкету", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ init_data: initData }) });
}

// «Давай жить вместе» — комната создаётся только после согласия приглашённого.
export async function createInvite(fromProfileId, toProfileId, capacity) {
  return requestJSON(`${BASE}/invites`, "Не удалось отправить приглашение", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({
      from_profile_id: fromProfileId,
      to_profile_id: toProfileId,
      capacity,
    }),
  });
}

export async function fetchMyInvites(profileId) {
  return read(`/profiles/${profileId}/invites?status=pending`, "Не удалось загрузить приглашения");
}

export async function respondInvite(inviteId, profileId, accept) {
  return requestJSON(`${BASE}/invites/${inviteId}/respond`, "Не удалось ответить на приглашение", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ profile_id: profileId, accept }),
  });
}

export async function fetchProfile(id) {
  return read(`/profiles/${id}`, "Анкета не найдена");
}

/** Сводка для админки: сколько анкет, у скольких есть ник и бот. */
export async function fetchAdminStats() {
  return requestJSON(`${BASE}/admin/stats`, "Не удалось загрузить статистику", { headers: authHeaders() });
}

/**
 * Анкеты для модерации: свежие сверху, с поиском по имени, нику и номеру.
 * Обычная лента для этого не годится — она делится по полу и кампус-отелю.
 */
export async function fetchAdminProfiles(params = {}) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== "" && value !== null && value !== undefined) {
      qs.append(key, value);
    }
  }
  const query = qs.toString();
  return requestJSON(`${BASE}/admin/profiles${query ? `?${query}` : ""}`, "Не удалось загрузить анкеты", {
    headers: authHeaders(),
  });
}

/** Удалить чужую анкету — модерация: человека выводит из комнаты и уведомляет. */
export async function adminDeleteProfile(id) {
  return requestJSON(`${BASE}/admin/profiles/${id}`, "Не удалось удалить анкету", {
    method: "DELETE",
    headers: authHeaders(),
  });
}

/**
 * Просим бота прислать выгрузку файлом в чат.
 *
 * Не скачиваем в браузере: внутри Telegram на macOS и iOS скачанный файл
 * открыть нечем — таблица показывается пустой или не открывается вовсе.
 * Присланный ботом документ система открывает сама.
 */
export async function sendExport({ format, scope, campus }) {
  return (await requestJSON(`${BASE}/admin/export/send`, "Не удалось отправить выгрузку", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ format, scope, campus: campus || null }),
  })).filename;
}

export async function fetchConfig() {
  return read("/config", "Не удалось загрузить настройки");
}

export async function uploadPhoto(file) {
  const body = new FormData();
  body.append("file", file);
  return requestJSON(`${BASE}/uploads/photo`, "Не удалось загрузить фото", {
    method: "POST",
    headers: authHeaders(),
    body,
  });
}

// Вход через Telegram Login Widget (обычный веб)
export async function authTelegram(widgetUser) {
  return requestJSON(`${BASE}/auth/telegram`, "Telegram не подтвердил вход", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify(widgetUser),
  });
}

// Вход из Telegram Mini App (сайт открыт внутри Telegram)
export async function authTelegramWebApp(initData) {
  return requestJSON(`${BASE}/auth/telegram/webapp`, "Telegram не подтвердил вход", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify({ init_data: initData }),
  });
}

export async function createProfile(profile) {
  return requestJSON(`${BASE}/profiles`, "Не удалось создать профиль", {
    method: "POST",
    headers: JSON_HEADERS(),
    body: JSON.stringify(profile),
  });
}

export async function updateProfile(id, profile) {
  return requestJSON(`${BASE}/profiles/${id}`, "Не удалось сохранить анкету", {
    method: "PUT",
    headers: JSON_HEADERS(),
    body: JSON.stringify(profile),
  });
}

export async function deleteProfile(id) {
  return requestJSON(`${BASE}/profiles/${id}`, "Не удалось удалить анкету", {
    method: "DELETE",
    headers: authHeaders(),
  });
}
