import { useCallback, useEffect, useRef, useState } from 'react';
import { LatestRequest } from './request.mjs';

/** Independent feeds: a slow secondary tab never blocks the visible list. */
export function useRemoteList(key, scope, loader, enabled) {
  const slot = useRef(new LatestRequest());
  const task = useRef(loader); task.current = loader;
  const [state, setState] = useState({ scope: null, data: [], loading: false, loaded: false, error: '', errorStatus: 0 });
  const reload = useCallback(() => {
    if (!enabled) return Promise.resolve();
    setState(prev => ({ scope, data: prev.scope === scope ? prev.data : [], loaded: prev.scope === scope && prev.loaded, loading: true, error: '', errorStatus: 0 }));
    return slot.current.run(async signal => {
      const data = await task.current(signal);
      if (!Array.isArray(data)) throw new Error('Не получилось прочитать подборку. Попробуй обновить её ещё раз.');
      return data;
    },
      data => setState({ scope, data, loaded: true, loading: false, error: '', errorStatus: 0 }),
      error => setState(prev => ({ ...prev, loading: false, error: error.message, errorStatus: error.status || 0 })),
    );
  }, [key, scope, enabled]);
  useEffect(() => { reload(); return () => slot.current.cancel(); }, [reload]);
  const setData = useCallback(update => setState(prev => ({ ...prev, scope, data: typeof update === 'function' ? update(prev.scope === scope ? prev.data : []) : update })), [scope]);
  const current = state.scope === scope ? state : { scope, data: [], loaded: false, loading: enabled, error: '', errorStatus: 0 };
  return { ...current, reload, setData };
}

export function useDebouncedValue(value, delay = 200) {
  const [result, setResult] = useState(value);
  useEffect(() => { const timer = setTimeout(() => setResult(value), delay); return () => clearTimeout(timer); }, [value, delay]);
  return result;
}
