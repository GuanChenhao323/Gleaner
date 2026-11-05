(() => {
  const R = globalThis.CampusRadar;
  R.adapters.moodle = {
    id: 'moodle', private: true,
    scan() {
      const root = document.querySelector('#region-main,main,[role="main"]');
      if (!root) R.fail('page_not_ready');
      const here = new URL(location.href);
      const candidates = [], navigation = [];
      if (here.pathname.endsWith('/mod/assign/view.php') && /^\d+$/.test(here.searchParams.get('id') || '')) {
        const node = root.querySelector('#intro.activity-description, .activity-description');
        if (!node) R.fail('selection_missing');
        const fields = { course: root.querySelector('[data-shortname]')?.getAttribute('data-shortname') || '', datetime_text: R.text(root.querySelector('[data-region="activity-dates"],.activity-dates') || node), requirements: root.querySelector('.submission-requirements')?.textContent.trim() || '' };
        // Dates remain original text; Core interprets them. Activity ID comes from the original route.
        candidates.push(R.candidate('moodle', `assignment:${here.searchParams.get('id')}`, here.href, '#intro.activity-description, .activity-description', R.raw(node, fields, R.title(root))));
      } else {
        const seen = new Set();
        for (const a of root.querySelectorAll('a[href]')) {
          const u = new URL(a.getAttribute('href'), location.href);
          if (u.origin !== here.origin) continue;
          if (u.pathname.endsWith('/course/view.php')) navigation.push({ title: a.textContent.trim(), url: u.href });
          if (!u.pathname.endsWith('/mod/assign/view.php') || !/^\d+$/.test(u.searchParams.get('id') || '')) continue;
          const entity = `assignment:${u.searchParams.get('id')}`;
          if (seen.has(entity)) continue;
          seen.add(entity);
          const title = a.textContent.trim();
          candidates.push(R.candidate('moodle', entity, u.href, '#intro.activity-description, .activity-description', { title, text: title, fields: {} }, {}, true));
        }
      }
      return { candidates, navigation };
    },
  };
})();
