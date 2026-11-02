// WebViews may deny localStorage. The current visit should still work.
const fallback = new Map();
export function readStored(key) { if (fallback.has(key)) return fallback.get(key); try { return globalThis.localStorage.getItem(key); } catch { return null; } }
export function writeStored(key, value) { try { globalThis.localStorage.setItem(key, String(value)); fallback.delete(key); } catch { fallback.set(key, String(value)); } }
export function removeStored(key) { try { globalThis.localStorage.removeItem(key); fallback.delete(key); } catch { fallback.set(key, null); } }
