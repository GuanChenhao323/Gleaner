(() => {
  const R = globalThis.CampusRadar;
  R.adapters.fie = {
    id: 'fie', private: false,
    scan() {
      const root = document.querySelector('main,[role="main"],article');
      if (!root) R.fail('unsupported_dom');
      const candidates = [];
      const person = location.pathname.match(/\/person\/view\/id-(\d+)\.html$/);
      if (person) {
        const detail = root.querySelector('[data-person-id],article') || (root.matches('article,[data-person-id]') ? root : null);
        if (!detail) R.fail('unsupported_dom');
        const fields = { subtype: 'teacher_profile', ...R.labeled(detail, { role: /职称|職稱|角色/, department: /部门|部門/, office: /办公室|辦公室/, phone: /电话|電話/, email: /邮箱|電郵|Email/i }) };
        candidates.push(R.candidate('fie', `person:${person[1]}`, location.href, '[data-person-id],main article,[role="main"] article', R.raw(detail, fields)));
      } else {
        const seen = new Set();
        for (const a of root.querySelectorAll('a[href]')) {
          if (a.closest('nav,header,footer')) continue;
          const u = new URL(a.getAttribute('href'), location.href);
          const id = u.pathname.match(/\/person\/view\/id-(\d+)\.html$/)?.[1];
          if (!id || u.origin !== location.origin || seen.has(id)) continue;
          seen.add(id);
          const title = a.textContent.trim();
          if (!title) continue;
          candidates.push(R.candidate('fie', `person:${id}`, u.href, '[data-person-id],main article,[role="main"] article', { title, text: title, fields: { subtype: 'teacher_profile' } }, {}, true));
        }
      }
      return { candidates, navigation: [] };
    },
  };
})();
