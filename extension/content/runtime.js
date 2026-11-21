// Shared isolated-world helpers. No page framework variables, passwords or cookies.
(() => {
  if (globalThis.CampusRadar) return;
  const R = globalThis.CampusRadar = { adapters: {}, version: 1 };
  R.fail = (code) => { const e = new Error(code); e.code = code; throw e; };
  R.visible = (n) => {
    if (!n || n.closest('[hidden],[aria-hidden="true"]')) return false;
    for (let node = n; node && globalThis.getComputedStyle; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || ['hidden', 'collapse'].includes(style.visibility)) return false;
    }
    return true;
  };
  R.text = (node) => {
    if (!node) R.fail('selection_missing');
    const clone = node.cloneNode(true);
    clone.querySelectorAll('nav,header,footer,script,style,form,noscript,[aria-hidden="true"],[hidden]').forEach(n => n.remove());
    clone.querySelectorAll('p,div,h1,h2,h3,li,tr,dt,dd,br').forEach(n => n.appendChild(document.createTextNode('\n')));
    return clone.textContent.split('\n').map(s => s.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n');
  };
  R.title = (node) => (node?.querySelector('h1,h2,h3')?.textContent || document.querySelector('h1,h2')?.textContent || document.title).trim();
  R.raw = (node, fields = {}, title = R.title(node)) => {
    const text = R.text(node);
    if (!title || !text || /^(loading[.…\s]*|正在加载[.…\s]*)$/i.test(text)) R.fail('page_not_ready');
    if (text.length > 20000 || title.length > 300) R.fail('content_too_large');
    return { title, text, fields };
  };
  R.account = () => {
    const marked = document.querySelector('body[data-userid],body[data-account-id],.usermenu[data-userid],.usermenu [data-userid]');
    const id = marked?.getAttribute('data-userid') || marked?.getAttribute('data-account-id');
    const profile = document.querySelector('.usermenu a[href*="/user/profile.php"]');
    return id || (profile && new URL(profile.href, location.href).searchParams.get('id')) || '';
  };
  R.access = () => {
    if (/\/(login|sso|auth)(\/|\.|$)/i.test(location.pathname) || [...document.querySelectorAll('input[type="password"]')].some(R.visible)) R.fail('need_login');
    if (/not found|access denied|無權限|没有权限/i.test(document.title)) R.fail('selection_missing');
  };
  R.fixture = () => ['localhost', '127.0.0.1'].includes(location.hostname) && document.querySelector('meta[name="campus-radar-fixture"]')?.content;
  R.adapter = () => {
    const id = R.fixture() || ({ 'moodle.must.edu.mo': 'moodle', 'student-wmweb.must.edu.mo': 'student', 'fie.must.edu.mo': 'fie' })[location.hostname];
    if (!R.adapters[id]) R.fail('unsupported');
    return R.adapters[id];
  };
  R.candidate = (adapter, entity, url, selector, raw, view = {}, detail = false) => ({
    candidate_id: entity, entity_id: entity, raw, needs_detail: detail,
    locator: { url, frame_url: url, view },
    recipe: { adapter, version: 1, entity_id: entity, url, view, selector },
    supported: true, enabled: false,
  });
  R.labeled = (root, names) => {
    const out = {};
    for (const [key, pattern] of Object.entries(names)) {
      const direct = root.querySelector(`[data-field="${key}"]`);
      if (direct && R.visible(direct) && !direct.closest('nav,header,footer,form')) { out[key] = R.text(direct); continue; }
      for (const label of root.querySelectorAll('dt,th')) {
        if (!R.visible(label) || label.closest('nav,header,footer,form')) continue;
        if (pattern.test(label.textContent.trim()) && label.nextElementSibling) out[key] = R.text(label.nextElementSibling);
      }
    }
    return out;
  };
})();
