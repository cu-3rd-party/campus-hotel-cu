import { profilePhoto } from "../links.mjs";
import { useRef, useState } from "react";
import { uploadPhoto } from "../api.js";
import { downscaleImage } from "../downscale.js";

export default function PhotoPicker({ value, onChange, onError, onBusyChange, name }) {
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  async function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    onError?.("");
    setUploading(true);
    onBusyChange?.(true);
    try {
      if (!file.type.startsWith('image/')) throw new Error('Выбери фото JPG, PNG или WebP.');
      if (file.size > 20 * 1024 * 1024) throw new Error('Фото больше 20 МБ. Выбери снимок поменьше.');
      // Ужимаем прямо в браузере: с телефона иначе едут мегабайты, которые
      // сервер всё равно уменьшит, а на мобильном канале это минуты ожидания.
      const small = await downscaleImage(file);
      if (small.size > 5 * 1024 * 1024) throw new Error('Не удалось уменьшить фото до 5 МБ. Выбери снимок поменьше.');
      const { photo_url } = await uploadPhoto(small);
      onChange(photo_url);
    } catch (err) {
      onError?.(err.message);
    } finally {
      setUploading(false);
      onBusyChange?.(false);
      // Сбрасываем, чтобы повторный выбор того же файла тоже сработал.
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const initial = (name || "?").trim().charAt(0).toUpperCase() || "?";

  return (
    <div className="photo-picker">
      <div className="photo-picker__preview">
        {profilePhoto(value) ? (
          <img src={profilePhoto(value)} referrerPolicy="no-referrer" alt="Фото профиля" />
        ) : (
          <span className="photo-picker__initial">{initial}</span>
        )}
      </div>

      <div className="photo-picker__actions">
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={handleFile}
        />
        <button
          type="button"
          className="photo-picker__btn"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
        >
          {uploading ? "Загружаем…" : value ? "Заменить фото" : "Загрузить фото"}
        </button>
        {value && (
          <button
            type="button"
            className="photo-picker__remove"
            onClick={() => onChange("")}
            disabled={uploading}
          >
            Удалить
          </button>
        )}
        <p className="photo-picker__hint">JPG, PNG или WebP. Большие фото уменьшим перед отправкой.</p>
      </div>
    </div>
  );
}
