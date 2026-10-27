/* Merge overlapping reads; keep controls when their data did not change. */
(() => {
  const stamps = new WeakMap(), requestGroups = new WeakMap();
  function coalesce(load) {
    const groups = new Map();
    return function run(key, context, {fresh = false} = {}) {
      const previous = groups.get(key);
      if (previous) { if (fresh) previous.dirty = true; return previous.promise; }
      const entry = {dirty: false, promise: null};
      entry.promise = Promise.resolve().then(async () => {
        let result;
        do { entry.dirty = false; result = await load(context); } while (entry.dirty);
        return result;
      }).finally(() => { if (groups.get(key) === entry) groups.delete(key); });
      groups.set(key, entry); return entry.promise;
    };
  }
  function paint(host, input, render) {
    const stamp = JSON.stringify(input);
    if (stamps.get(host) === stamp) return false;
    render(); stamps.set(host, stamp); return true;
  }
  function reconcile(host, rows, {key, stamp, create, empty}) {
    const previous = new Map([...host.children].map(node => [node._sfRefreshKey, node]));
    const nodes = rows.map(row => {
      const id = key(row), signature = JSON.stringify(stamp(row)); let node = previous.get(id);
      if (!node || stamps.get(node) !== signature) { node = create(row); node._sfRefreshKey = id; stamps.set(node, signature); }
      return node;
    });
    if (!nodes.length && empty) {
      let node = previous.get('__empty__');
      if (!node) { node = empty(); node._sfRefreshKey = '__empty__'; } nodes.push(node);
    }
    for (const [index, node] of nodes.entries()) {
      const before = host.children[index] || null;
      if (before !== node) {
        if (host.moveBefore && node.parentElement === host) host.moveBefore(node, before);
        else host.insertBefore(node, before);
      }
    }
    const wanted = new Set(nodes); for (const node of [...host.children]) if (!wanted.has(node)) node.remove();
  }
  function shared(api, key, operation) {
    let group = requestGroups.get(api); if (!group) { group = new Map(); requestGroups.set(api, group); }
    if (!group.has(key)) group.set(key, Promise.resolve().then(operation).finally(() => group.delete(key)));
    return group.get(key);
  }
  async function pollTask(api, id, {detailOnFinish = true} = {}) {
    const path = '/api/jobs/' + encodeURIComponent(id);
    const summary = await shared(api, path + ':progress', () => api(path + '?view=progress'));
    if (detailOnFinish && ['completed', 'failed', 'paused', 'cancelled'].includes(summary.status))
      return shared(api, path + ':detail', () => api(path));
    return summary;
  }
  window.studyforgeRefresh = {coalesce, paint, reconcile, pollTask};
})();
