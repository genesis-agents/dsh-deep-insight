  export async function api(sessionId, signal, body) {
    const response = await fetch('/deep-insight/api?session=' + encodeURIComponent(sessionId), body ? { method: 'POST', signal, headers: { 'content-type': 'application/json', 'x-deep-insight-client': '1' }, body: JSON.stringify(body) } : { signal, cache: 'no-store' })
    const value = await response.json()
    if (!response.ok) throw new Error(value.error?.message ?? `HTTP ${response.status}`)
    return value
  }
  export function createFeed(sessionId, load = api) {
    const feedView = { tab: 'overview', selected: null }
    let snapshot = { state: null, error: null, syncedAt: null }, timer, pending, disposed = false
    const listeners = new Set(), controller = new AbortController()
    const publish = value => { snapshot = { ...snapshot, ...value }; for (const listener of listeners) listener() }
    const poll = () => {
      if (pending || disposed) return pending
      clearTimeout(timer)
      pending = load(sessionId, controller.signal).then(state => { if (!disposed) publish({ state, error: null, syncedAt: new Date() }) }, error => { if (!disposed) publish({ error: error.message }) })
        .finally(() => { pending = null; if (!disposed && listeners.size) timer = setTimeout(poll, 3000) })
      return pending
    }
    return {
      view: feedView,
      getSnapshot: () => snapshot,
      subscribe: listener => {
        listeners.add(listener)
        if (!snapshot.syncedAt || Date.now() - snapshot.syncedAt.getTime() > 3000) void poll()
        else if (!timer && !pending) timer = setTimeout(poll, 3000)
        return () => { listeners.delete(listener); if (!listeners.size) { clearTimeout(timer); timer = null } }
      },
      refresh: poll,
      chooseRun: selected => { Object.assign(feedView, { selected }); publish({}) },
      active: () => listeners.size > 0,
      fail: error => publish({ error }),
      dispose: () => { disposed = true; controller.abort(); clearTimeout(timer); listeners.clear() },
    }
  }
