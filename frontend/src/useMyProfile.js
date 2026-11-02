import { useCallback, useEffect, useState } from "react";
import { fetchMyProfileByTelegram, fetchProfile } from "./api.js";
import { readStored, writeStored, removeStored } from "./storage.mjs";
import { getInitData, isInsideTelegram } from "./telegram.js";

const KEY = "obshaga_my_profile_id";

/**
 * «Моя анкета».
 *
 * Внутри Telegram личность определяет подпись initData — это надёжно и
 * переживает смену устройства и очистку кэша. localStorage остаётся
 * запасным вариантом для обычного браузера, где подписи нет.
 */
export function useMyProfile() {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    // 1) Мини-апп: спрашиваем сервер «кто я» по подписи Telegram.
    if (isInsideTelegram()) {
      try {
        const mine = await fetchMyProfileByTelegram(getInitData());
        writeStored(KEY, String(mine.id));
        setProfile(mine);
        return mine;
      } catch {
        // 404 — анкеты действительно нет. Пробуем localStorage ниже:
        // анкету могли создать в браузере без входа через Telegram.
      } finally {
        setLoading(false);
      }
    }

    // 2) Обычный браузер (или анкета без привязки к Telegram).
    const id = readStored(KEY);
    if (!id) {
      setProfile(null);
      setLoading(false);
      return null;
    }
    try {
      const fresh = await fetchProfile(id);
      setProfile(fresh);
      return fresh;
    } catch (error) {
      if (error.status === 404) { removeStored(KEY); setProfile(null); }
      // An unavailable server is not evidence that the saved profile was deleted.
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const remember = useCallback((created) => {
    writeStored(KEY, String(created.id));
    setProfile(created);
  }, []);

  const forget = useCallback(() => {
    removeStored(KEY);
    setProfile(null);
  }, []);

  return { myProfile: profile, loadingMe: loading, remember, forget, reloadMe: reload };
}
