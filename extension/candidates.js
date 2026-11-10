// 候选事项识别（IC-001 3.1，决策 D19）：弹窗注入当前页面时用它列出候选事项，
// 后台监测在 offscreen 文档里解析重新获取的页面时也用它，按同一个 locator 找回事项。
// 同一事项每次识别必须得到相同的 locator：
//   Moodle 活动   cmid:<id>      （/mod/<模块>/view.php?id=<id>）
//   Moodle 讨论   forum:d:<id>   （/mod/forum/discuss.php?d=<id>）
//   普通列表条目  href:<路径与查询>（条目自己的链接，去掉 #片段）
//   整页          page
// 只有标题可用时由弹窗用标题哈希生成 t:<12 位>，这类事项不支持监测（标题一改就找不到）。
(() => {
  const MAX_CANDIDATES = 100;
  // 这些 Moodle 活动通常要求学生提交或完成，默认判为待办；其余活动判为通知
  const TODO_MODS = new Set(["assign", "quiz", "workshop", "lesson", "choice", "feedback", "h5pactivity", "lti", "scorm"]);
  const SKIP = "nav, header, footer, aside, .navbar, .breadcrumb, #nav-drawer, .block, .drawer, [role=navigation]";

  const norm = (s) => String(s || "").replace(/\s+/g, " ").trim();
  const lines = (s) =>
    String(s || "")
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .join("\n");

  function abs(href, base) {
    try {
      const u = new URL(href, base);
      u.hash = "";
      return u.href;
    } catch {
      return "";
    }
  }

  function moodleRef(url) {
    let m = /\/mod\/(\w+)\/view\.php\?(?:[^#]*&)?id=(\d+)/.exec(url);
    if (m) return { locator: `cmid:${m[2]}`, type: TODO_MODS.has(m[1]) ? "todo" : "notice" };
    m = /\/mod\/forum\/discuss\.php\?(?:[^#]*&)?d=(\d+)/.exec(url);
    if (m) return { locator: `forum:d:${m[1]}`, type: "notice" };
    return null;
  }

  function isMoodle(doc) {
    const gen = doc.querySelector('meta[name="generator"]');
    if (gen && /moodle/i.test(gen.content || "")) return true;
    const body = doc.body;
    return !!(body && /^page-/.test(body.id || "") && doc.querySelector('a[href*="/mod/"], [data-region="activity-dates"], #region-main'));
  }

  function mainOf(doc) {
    return doc.querySelector('#region-main, [role="main"], main, article, #content, .content') || doc.body;
  }

  // innerText 依赖布局，offscreen 文档里不可靠：没有 innerText 时用 textContent 并按块元素断行
  function textOf(el) {
    if (!el) return "";
    if (typeof el.innerText === "string" && el.innerText.trim()) return lines(el.innerText);
    const clone = el.cloneNode(true);
    clone.querySelectorAll("script, style, noscript, template").forEach((n) => n.remove());
    clone.querySelectorAll("br, p, div, li, tr, h1, h2, h3, h4, h5, h6, dt, dd").forEach((n) => n.append("\n"));
    return lines(clone.textContent);
  }

  function titleOf(link) {
    const inst = link.querySelector(".instancename");
    if (inst) {
      const c = inst.cloneNode(true);
      c.querySelectorAll(".accesshide, .sr-only").forEach((n) => n.remove());
      return norm(c.textContent);
    }
    return norm(link.textContent) || norm(link.getAttribute("title")) || norm(link.getAttribute("aria-label"));
  }

  function containerOf(link, root) {
    const box = link.closest(
      'tr, li, article, .activity, .activity-item, [data-region="activity-card"], .card, .discussion, .news-item, .list-item',
    );
    return box && root.contains(box) && box !== root ? box : link.parentElement || link;
  }

  function pageTitle(doc) {
    const og = doc.querySelector('meta[property="og:title"]');
    const h = mainOf(doc).querySelector("h1, h2");
    return norm((og && og.content) || (h && h.textContent) || doc.title);
  }

  function extract(doc, pageUrl, maxText) {
    maxText = maxText || 100000;
    const root = mainOf(doc);
    const moodle = isMoodle(doc);
    const out = [];
    const seen = new Set();
    const push = (c) => {
      if (!c.locator || seen.has(c.locator) || !c.title || out.length >= MAX_CANDIDATES) return;
      seen.add(c.locator);
      out.push({ ...c, text: String(c.text || "").slice(0, maxText) });
    };

    const self = moodle ? moodleRef(pageUrl) : null;
    if (self) {
      // 活动页或讨论页本身就是一条事项
      push({ locator: self.locator, type: self.type, title: pageTitle(doc), text: textOf(root), url: pageUrl });
    } else {
      for (const a of root.querySelectorAll("a[href]")) {
        if (a.closest(SKIP)) continue;
        const url = abs(a.getAttribute("href"), pageUrl);
        if (!/^https?:/i.test(url) || url === abs(pageUrl, pageUrl)) continue;
        const ref = moodle ? moodleRef(url) : null;
        if (moodle && !ref) continue; // Moodle 页面只认活动与讨论链接，课程导航、用户链接等不算
        const box = containerOf(a, root);
        const text = textOf(box);
        const title = titleOf(a);
        if (!ref && (title.length < 4 || text.length < 6)) continue;
        if (ref) {
          push({ locator: ref.locator, type: ref.type, title, text, url });
        } else {
          const u = new URL(url);
          push({ locator: `href:${u.pathname}${u.search}`, title, text, url });
        }
      }
      // 普通网页只有一两个链接时多半不是列表页，不当作多条事项
      if (!moodle && out.length < 2) out.length = 0;
    }
    const whole = { locator: "page", title: pageTitle(doc) || pageUrl, text: textOf(root).slice(0, maxText), url: pageUrl };
    const feeds = [...doc.querySelectorAll('link[rel="alternate"]')]
      .filter((l) => /rss|atom/i.test(l.type || "") && l.getAttribute("href"))
      .map((l) => ({ href: abs(l.getAttribute("href"), pageUrl), title: l.title || "" }));
    return { url: pageUrl, title: whole.title, platform: moodle ? "moodle" : "web", candidates: out, page: whole, feeds };
  }

  // 是否像登录页：后台监测拿到它说明会话已过期，不能当成“内容消失”
  function looksLikeLogin(doc, finalUrl) {
    if (/\/login\/|\/cas\/login|[?&]service=/i.test(finalUrl || "")) return true;
    return !!doc.querySelector('form#login, form[action*="login"] input[type="password"], #loginbtn');
  }

  globalThis.gleanerCandidates = { extract, looksLikeLogin, moodleRef };
})();
