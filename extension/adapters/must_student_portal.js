// DOM profile v1 is fixture-verified, not a claim about the unobserved WeMust DOM.
// Unknown production markup fails closed; no invented private API or route is called.
(() => {
  const R = globalThis.CampusRadar;
  R.adapters.student = {
    id: 'student', private: true,
    scan() {
      const root = document.querySelector('main,[role="main"]');
      if (!root) R.fail(document.querySelector('iframe') ? 'frame_unsupported' : 'page_not_ready');
      const candidates = [];
      const view = { route: location.hash, query: location.search };
      for (const key of ['semester', 'week']) {
        const n = root.matches(`[data-${key}]`) ? root : root.querySelector(`[data-${key}],select[name="${key}"]`);
        if (n) view[key] = n.getAttribute(`data-${key}`) || n.value;
      }
      for (const node of root.querySelectorAll('[data-notice-id],[data-schedule-id]')) {
        if (!R.visible(node) || node.closest('nav,footer,header')) continue;
        const schedule = node.hasAttribute('data-schedule-id');
        const native = node.getAttribute(schedule ? 'data-schedule-id' : 'data-notice-id');
        if (!native || /\s/.test(native)) continue;
        const entity = `${schedule ? 'timetable' : 'notice'}:${native}`;
        const fields = R.labeled(node, { course: /课程|課程/, semester: /学期|學期/, week: /周次|週次/, weekday: /星期/, period: /节次|節次/, datetime_text: /日期|时间|時間/ });
        if (schedule) Object.assign(fields, { subtype: 'timetable', ...view });
        // route/query belong in locator.view, not the semantic raw field dictionary.
        delete fields.route; delete fields.query;
        const selector = `[${schedule ? 'data-schedule-id' : 'data-notice-id'}=${JSON.stringify(native)}]`;
        const link = node.querySelector('a[data-detail][href]');
        const url = link ? new URL(link.getAttribute('href'), location.href).href : location.href;
        const targetView = { ...view, route: new URL(url).hash, query: new URL(url).search };
        candidates.push(R.candidate('student', entity, url, selector, R.raw(node, fields), targetView, Boolean(link)));
      }
      if (!candidates.length) R.fail(document.querySelector('iframe') ? 'frame_unsupported' : 'unsupported_dom');
      return { candidates, navigation: [] };
    },
  };
})();
