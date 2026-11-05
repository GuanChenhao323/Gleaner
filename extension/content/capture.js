(() => {
  const R = globalThis.CampusRadar;
  R.scan = () => {
    R.access();
    const adapter = R.adapter();
    const page = adapter.scan();
    const account = adapter.private ? R.account() : 'public';
    return { ...page, adapter: adapter.id, account, url: location.href,
      capability: account ? 'fixture_or_structural_match' : 'account_unknown' };
  };
  R.capture = (recipe) => {
    const page = R.scan();
    if (page.adapter !== recipe.adapter) R.fail('unsupported');
    const found = page.candidates.find(c => c.entity_id === recipe.entity_id);
    if (!found || found.needs_detail) R.fail('selection_missing');
    const view = v => JSON.stringify(Object.entries(v || {}).sort(([a], [b]) => a.localeCompare(b)));
    if (view(found.recipe.view) !== view(recipe.view)) R.fail('view_mismatch');
    if (location.href !== recipe.url) R.fail('route_mismatch');
    if (document.querySelectorAll(recipe.selector).length !== 1) R.fail('selection_missing');
    return { ...found, account: page.account, adapter: page.adapter };
  };
  R.wait = async (recipe, timeout = 12000) => {
    const until = Date.now() + timeout;
    let prior = '', stable = 0, error = 'render_timeout';
    while (Date.now() < until) {
      try {
        const value = recipe ? R.capture(recipe) : R.scan();
        const key = JSON.stringify(value);
        if (key === prior) stable++; else stable = 0;
        if (stable >= 2) return value;
        prior = key;
      } catch (e) {
        error = e.code || e.message;
        if (['need_login', 'account_unknown', 'unsupported', 'frame_unsupported', 'content_too_large'].includes(error)) throw e;
      }
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    R.fail(['selection_missing', 'route_mismatch', 'view_mismatch'].includes(error) ? error : 'render_timeout');
  };
  R.highlight = (recipe) => {
    const node = document.querySelector(recipe.selector);
    if (node) { node.style.outline = '3px solid #2f6b5a'; node.scrollIntoView?.({ block: 'nearest' }); }
  };
  R.manual = () => {
    R.access();
    const selected = String(getSelection()).trim();
    const anchor = getSelection()?.anchorNode?.parentElement?.closest('[id]');
    if (!selected || !anchor?.id || anchor.closest('nav,header,footer,form') || !R.text(anchor).includes(selected)) R.fail('selection_missing');
    const selector = `[id=${JSON.stringify(anchor.id)}]`;
    const raw = { title: document.title, text: R.text(anchor), fields: {} };
    if (raw.text.length > 20000) R.fail('content_too_large');
    // Preview the entire stable element; do not silently change a text selection's range.
    return R.candidate('manual', `manual:${anchor.id}`, location.href, selector, raw, { route: location.hash });
  };
  R.adapters.manual = { id: 'manual', private: true, scan() {
    const id = new URL(location.href).hash;
    return { candidates: [], navigation: [], id };
  } };
})();
