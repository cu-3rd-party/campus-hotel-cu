/** Legacy profile fields are still untrusted even when rendered by React. */
export function telegramLink(value) {
  const username = String(value || '').trim().replace(/^@/, '');
  return /^[A-Za-z0-9_]{1,32}$/.test(username) ? `https://t.me/${username}` : undefined;
}

export function profilePhoto(value) {
  if (typeof value !== 'string') return '';
  if (/^\/api\/media\/[a-f0-9]{32}\.jpg$/.test(value)) return value;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && !/\s/.test(value) ? url.href : '';
  } catch { return ''; }
}
