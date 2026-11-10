// 后台监测（IC-001 3.2、3.3，决策 D23）：Chrome 运行时由 alarms 定期唤醒，
// 向本地后端领取到期任务，用浏览器自己的登录会话重新读取页面，按 locator 找回事项后回报结果。
// 不导出 Cookie、不把页面交给第三方；只读 GET；同一主机请求间隔不少于 2 秒；遵守 robots.txt。
// 失败一律如实回报（登录过期、无权限、网络、找不到、解析失败），后端不会把失败显示成“无变化”。

const ALARM = "gleaner-monitor";
const PERIOD_MIN = 5; // 每 5 分钟问一次后端有没有到期任务；真正的检查间隔由后端决定（默认 1 小时）
const HOST_GAP_MS = 2000;
const FETCH_TIMEOUT_MS = 30000;
const MAX_HTML = 8 * 1024 * 1024;
const ROBOTS_TTL_MS = 3600 * 1000;

const lastHit = new Map(); // host -> 上次请求开始时间
const robotsCache = new Map(); // origin -> { at, rules | null(不可达) }
let running = null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function ensureAlarm() {
  // service worker 随时可能被回收；每次启动都检查 alarm 是否还在（IC-003 4.2）
  const a = await chrome.alarms.get(ALARM);
  if (!a) await chrome.alarms.create(ALARM, { delayInMinutes: 1, periodInMinutes: PERIOD_MIN });
}

chrome.runtime.onInstalled.addListener(ensureAlarm);
chrome.runtime.onStartup.addListener(ensureAlarm);
ensureAlarm();

chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === ALARM) runOnce();
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "monitor-kick") runOnce();
});

function runOnce() {
  if (!running) running = check().finally(() => (running = null));
  return running;
}

async function config() {
  const s = await chrome.storage.local.get(["server", "token"]);
  return { server: s.server || "", token: s.token || "" };
}

async function api(cfg, path, body) {
  const res = await fetch(cfg.server + path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.token}` },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`backend HTTP ${res.status}`);
  return res.json();
}

async function check() {
  const cfg = await config();
  if (!cfg.server || !cfg.token) return;
  let due;
  try {
    due = await api(cfg, "/api/monitor/due?limit=20");
  } catch {
    return; // 后端没运行或令牌失效：什么都不做，下次再试（弹窗里会提示重新登录）
  }
  const byPage = new Map();
  for (const t of due.tasks || []) {
    if (!byPage.has(t.page_url)) byPage.set(t.page_url, []);
    byPage.get(t.page_url).push(t);
  }
  const results = [];
  for (const [pageUrl, tasks] of byPage) {
    // 同一页面上的多条事项只取一次页面（IC-003 4.4）
    results.push(...(await checkPage(pageUrl, tasks)));
  }
  for (let i = 0; i < results.length; i += 50) {
    try {
      await api(cfg, "/api/monitor/results", { results: results.slice(i, i + 50) });
    } catch {
      // 回报失败：租期到了后端会重新发这些任务
    }
  }
}

const fail = (tasks, code, message) =>
  tasks.map((t) => ({ item_id: t.item_id, ok: false, error: { code, message } }));

async function checkPage(pageUrl, tasks) {
  let url;
  try {
    url = new URL(pageUrl);
  } catch {
    return fail(tasks, "unsupported", "地址无效");
  }
  if (!(await chrome.permissions.contains({ origins: [url.origin + "/*"] }))) {
    return fail(tasks, "forbidden", "插件没有访问该网站的权限，请在弹窗里重新保存并允许访问");
  }
  const robots = await robotsFor(url.origin);
  if (robots === null) return fail(tasks, "network", "暂时取不到 robots.txt，稍后再试");
  if (!robotsAllowed(robots, url.pathname + url.search)) {
    return fail(tasks, "unsupported", "该网站的 robots.txt 不允许自动访问这个页面");
  }
  let res;
  let html;
  try {
    res = await politeFetch(pageUrl);
    if (res.status === 401) return fail(tasks, "auth_expired", "登录已过期，请在浏览器里重新登录该网站");
    if (res.status === 403) return fail(tasks, "forbidden", "没有权限访问该页面（HTTP 403）");
    if (res.status === 404 || res.status === 410) return fail(tasks, "not_found", `页面不存在（HTTP ${res.status}）`);
    if (!res.ok) return fail(tasks, "network", `网站返回 HTTP ${res.status}`);
    if (!/html|xml/i.test(res.headers.get("Content-Type") || "")) {
      return fail(tasks, "parse_failed", "页面不是网页格式，无法检查");
    }
    const len = Number(res.headers.get("Content-Length") || 0);
    if (len > MAX_HTML) return fail(tasks, "parse_failed", "页面太大");
    html = (await res.text()).slice(0, MAX_HTML);
  } catch (e) {
    return fail(tasks, "network", e.name === "AbortError" ? "请求超时" : "网络错误");
  }
  let parsed;
  try {
    parsed = await parseInOffscreen(html, res.url || pageUrl, pageUrl);
  } catch {
    return fail(tasks, "parse_failed", "无法解析页面");
  }
  if (parsed.login) return fail(tasks, "auth_expired", "登录已过期，请在浏览器里重新登录该网站");
  const found = new Map(parsed.result.candidates.map((c) => [c.locator, c]));
  found.set("page", parsed.result.page);
  return tasks.map((t) => {
    const c = found.get(t.locator);
    if (!c) return { item_id: t.item_id, ok: false, error: { code: "not_found", message: "页面上找不到这条事项" } };
    return {
      item_id: t.item_id,
      ok: true,
      title: c.title,
      text: c.text || "",
      url: c.url || pageUrl,
      ...(c.type ? { type: c.type } : {}),
    };
  });
}

async function politeFetch(url) {
  const host = new URL(url).host;
  const wait = (lastHit.get(host) || 0) + HOST_GAP_MS - Date.now();
  if (wait > 0) await sleep(wait);
  lastHit.set(host, Date.now());
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), FETCH_TIMEOUT_MS);
  try {
    // 用浏览器的会话读取（只读 GET），重定向由浏览器跟随；跳到登录页会在解析时识别出来
    return await fetch(url, { credentials: "include", cache: "no-store", redirect: "follow", signal: ctl.signal });
  } finally {
    clearTimeout(timer);
  }
}

// ---- robots.txt（RFC 9309 的精简实现：* 组与 gleaner 组、Allow/Disallow、* 与 $、最长匹配） ----

async function robotsFor(origin) {
  const hit = robotsCache.get(origin);
  if (hit && Date.now() - hit.at < ROBOTS_TTL_MS) return hit.rules;
  let rules;
  try {
    const res = await politeFetch(origin + "/robots.txt");
    if (res.status >= 500) rules = null;
    else if (res.ok) rules = parseRobots(await res.text());
    else rules = []; // 4xx：没有限制
  } catch {
    rules = null; // 不可达：视为全部禁止，稍后再试
  }
  robotsCache.set(origin, { at: rules === null ? Date.now() - ROBOTS_TTL_MS + 300000 : Date.now(), rules });
  return rules;
}

function parseRobots(text) {
  const groups = [];
  let cur = null;
  let lastAgent = false;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.split("#")[0].trim();
    const i = line.indexOf(":");
    if (i < 0) continue;
    const k = line.slice(0, i).trim().toLowerCase();
    const v = line.slice(i + 1).trim();
    if (k === "user-agent") {
      if (!cur || !lastAgent) groups.push((cur = { agents: [], rules: [] }));
      cur.agents.push(v.toLowerCase());
      lastAgent = true;
      continue;
    }
    lastAgent = false;
    if (cur && (k === "allow" || k === "disallow") && v) cur.rules.push({ allow: k === "allow", path: v });
  }
  const mine = groups.filter((g) => g.agents.some((a) => a && a !== "*" && "gleaner".includes(a)));
  const chosen = mine.length ? mine : groups.filter((g) => g.agents.includes("*"));
  return chosen.flatMap((g) => g.rules);
}

function robotsAllowed(rules, path) {
  let best = null;
  for (const r of rules) {
    const anchored = r.path.endsWith("$");
    const body = anchored ? r.path.slice(0, -1) : r.path;
    const rx = new RegExp("^" + body.split("*").map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join(".*") + (anchored ? "$" : ""));
    if (rx.test(path)) {
      const cand = [r.path.length, r.allow ? 1 : 0];
      if (!best || cand[0] > best[0] || (cand[0] === best[0] && cand[1] > best[1])) best = cand;
    }
  }
  return !best || best[1] === 1;
}

// ---- offscreen 文档：service worker 里没有 DOMParser ----

async function ensureOffscreen() {
  const has = chrome.offscreen.hasDocument ? await chrome.offscreen.hasDocument() : false;
  if (has) return;
  try {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["DOM_PARSER"],
      justification: "解析重新获取的网页，按定位符找回已保存的事项",
    });
  } catch (e) {
    if (!/single offscreen/i.test(String(e))) throw e;
  }
}

async function parseInOffscreen(html, finalUrl, pageUrl) {
  await ensureOffscreen();
  const r = await chrome.runtime.sendMessage({ target: "offscreen", type: "parse", html, finalUrl, pageUrl });
  if (!r || r.error) throw new Error(r ? r.error : "no response");
  return r;
}
