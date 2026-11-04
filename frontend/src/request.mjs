/** One request, one deadline. Mutations are never retried automatically. */
export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.name = 'ApiError'; this.status = status; }
}

function errorMessage(data, fallback) {
  if (typeof data?.detail === 'string') return data.detail;
  const issue = Array.isArray(data?.detail) ? data.detail[0] : null;
  const field = issue?.loc?.at(-1);
  const labels = {name:'Имя', telegram:'Telegram', bio:'О себе', photo_url:'Фото'};
  if (!labels[field]) return fallback;
  if (issue.type === 'string_too_long') return `Поле «${labels[field]}» слишком длинное. Сократи текст и попробуй ещё раз.`;
  return `Проверь поле «${labels[field]}» и попробуй ещё раз.`;
}

export async function requestJSON(url, fallback, options = {}, timeoutMs = 12000) {
  const controller = new AbortController();
  const cancel = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) cancel();
  else options.signal?.addEventListener('abort', cancel, { once: true });
  let expired = false;
  const timer = setTimeout(() => { expired = true; controller.abort(); }, timeoutMs);
  try {
    const response = await globalThis.fetch(url, { ...options, signal: controller.signal });
    const data = response.status === 204 ? null : await response.json().catch(error => {
      if (controller.signal.aborted) throw error;
      if (response.ok) throw new ApiError(fallback, response.status);
      return null;
    });
    if (!response.ok) throw new ApiError(errorMessage(data, fallback), response.status);
    return data;
  } catch (error) {
    if (expired) throw new ApiError(options.method && options.method !== 'GET' ? 'Ответ сервера задержался. Обнови список и проверь результат перед повторной отправкой.' : 'Сервер отвечает дольше обычного. Попробуй обновить ещё раз.');
    if (options.signal?.aborted) throw error;
    if (error instanceof ApiError) throw error;
    throw new ApiError(fallback);
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', cancel);
  }
}

/** Guards React state even when a transport ignores AbortSignal. */
export class LatestRequest {
  sequence = 0;
  controller = null;
  cancel() { this.sequence++; this.controller?.abort(); }
  async run(loader, commit, fail, finish = () => {}) {
    this.cancel();
    const sequence = this.sequence;
    const controller = this.controller = new AbortController();
    try {
      const result = await loader(controller.signal);
      if (sequence === this.sequence && !controller.signal.aborted) commit(result);
      return result;
    } catch (error) {
      if (sequence === this.sequence && !controller.signal.aborted) fail(error);
    } finally {
      if (sequence === this.sequence && !controller.signal.aborted) finish();
    }
  }
}
