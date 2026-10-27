(() => {
  // Copy this file into a project and load it locally with data-project="tempo".
  // Only the daily, project-specific hash leaves this browser; the seed stays here.
  const script = document.currentScript;
  const project = script?.dataset?.project;
  if (!['tempo', 'cunder', 'ekmod', 'disk', 'math', 'finance'].includes(project)) return;
  const projectOrigins = {
    tempo: ['https://tennis.cu.vubni.ru'],
    cunder: ['https://cunder.ru', 'https://cunder.cu.vubni.ru'],
    ekmod: ['https://ecmod.cu.vubni.ru'],
    disk: ['https://disk.cu-politic.ru'],
    math: ['https://math.cu.vubni.ru'],
    finance: ['https://finance.cu.vubni.ru']
  };
  let endpoint;
  try {
    const url = new URL(script.dataset.endpoint || 'https://cu.vubni.ru');
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) return;
    if (!['https:', 'http:'].includes(window.location.protocol)) return;
    const localHosts = new Set(['localhost', '127.0.0.1', '[::1]']);
    const localTest = script.dataset.endpoint && localHosts.has(window.location.hostname) && localHosts.has(url.hostname);
    if (!projectOrigins[project].includes(window.location.origin) && !localTest) return;
    endpoint = url.href.replace(/\/+$/, '');
    if (!crypto.subtle || typeof crypto.subtle.digest !== 'function') return;
  } catch { return; }

  const key = 'cu-hub-visitor-seed';
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const createSeed = () => {
    try {
      if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 15) | 64;
      bytes[8] = (bytes[8] & 63) | 128;
      const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    } catch { return null; }
  };
  let seed;
  for (const storageName of ['localStorage', 'sessionStorage']) {
    try {
      const storage = window[storageName];
      const saved = storage.getItem(key);
      if (typeof saved === 'string' && uuidPattern.test(saved)) {
        seed = saved;
        break;
      }
      const fresh = createSeed();
      if (!fresh) return;
      storage.setItem(key, fresh);
      seed = fresh;
      break;
    } catch { /* A session or in-memory seed still allows approximate counting. */ }
  }
  if (!seed) seed = createSeed();
  if (!seed) return;

  const moscowDay = () => new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const sent = new Set();
  const pending = new Set();
  const report = async () => {
    if (document.visibilityState !== 'visible' || navigator.onLine === false) return;
    const day = moscowDay();
    if (sent.has(day) || pending.has(day)) return;
    pending.add(day);
    try {
      const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${project}|${day}|${seed}`));
      if (document.visibilityState !== 'visible' || navigator.onLine === false || day !== moscowDay()) return;
      const visitorId = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
      const response = await fetch(`${endpoint}/api/visits/${project}`, {
        method: 'POST', mode: 'cors', credentials: 'omit', keepalive: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ day, visitorId })
      });
      if (response.ok) sent.add(day);
    } catch { /* Visiting the project never depends on the statistics service. */ }
    finally { pending.delete(day); }
  };
  document.addEventListener('visibilitychange', report);
  window.addEventListener('focus', report);
  window.addEventListener('online', report);
  setInterval(report, 60 * 1000);
  void report();
})();
