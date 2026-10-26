// 拾课浏览器插件弹窗：保存当前页面到收件箱、订阅页面更新。
// 只在用户点开弹窗时读取当前标签页（activeTab），只对用户填写的拾课服务器申请访问权限。

const MAX_TEXT = 100000; // 与服务端 CLIP_MAX_TEXT 一致

const $ = (id) => document.getElementById(id);
let cfg = { server: "", token: "", email: "" };
let page = null; // { title, url, text, selection, feeds }

function setStatus(text, kind = "") {
  const el = $("status");
  el.textContent = text;
  el.className = kind;
}

function busy(on) {
  for (const id of ["login", "save", "subscribe"]) $(id).disabled = on;
}

async function loadConfig() {
  const s = await chrome.storage.local.get(["server", "token", "email"]);
  cfg = { server: s.server || "", token: s.token || "", email: s.email || "" };
}

async function saveConfig(patch) {
  cfg = { ...cfg, ...patch };
  await chrome.storage.local.set(cfg);
}

function normalizeServer(raw) {
  const u = new URL(raw.trim());
  if (u.protocol !== "http:" && u.protocol !== "https:") throw new Error("服务器地址要以 http:// 或 https:// 开头");
  return u.origin;
}

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, body) {
  const res = await fetch(cfg.server + path, {
    method: body ? "POST" : "GET",
    headers: {
      "Content-Type": "application/json",
      ...(cfg.token ? { Authorization: `Bearer ${cfg.token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try {
    data = await res.json();
  } catch {
    // 非 JSON 响应（例如网关 502 页面）
  }
  if (!res.ok || data.ok === false) {
    const msg = typeof data.error === "string" ? data.error : data.message || `请求失败（HTTP ${res.status}）`;
    throw new ApiError(res.status, msg);
  }
  return data;
}

// 在页面里执行：读取标题、正文、选中文字、页面声明的 RSS / Atom
function extractPage(maxText) {
  const pick = (sel) => document.querySelector(sel);
  const og = pick('meta[property="og:title"]');
  const title = (og && og.content) || document.title || location.href;
  const selection = String(window.getSelection() || "").trim();
  const root = pick("main, article, [role=main]") || document.body;
  const text = (root ? root.innerText : "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join("\n")
    .slice(0, maxText);
  const feeds = [...document.querySelectorAll('link[rel="alternate"]')]
    .filter((l) => /rss|atom/i.test(l.type || "") && l.href)
    .map((l) => ({ href: new URL(l.href, location.href).href, title: l.title || "" }));
  return { title: title.trim(), url: location.href, text, selection: selection.slice(0, maxText), feeds };
}

async function readActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https?:/i.test(tab.url || "")) {
    throw new Error("这个页面不能加入拾课（只支持 http / https 网页）");
  }
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: extractPage, args: [MAX_TEXT] });
    return res.result;
  } catch {
    // 浏览器商店、PDF 等页面不允许注入脚本：仍可保存标题和网址
    return { title: tab.title || tab.url, url: tab.url, text: "", selection: "", feeds: [] };
  }
}

function showLogin() {
  $("login-view").hidden = false;
  $("main-view").hidden = true;
  $("footer").hidden = true;
  $("account").textContent = "";
  $("server").value = cfg.server || "http://localhost:8080";
  $("email").value = cfg.email || "";
}

async function showMain() {
  $("login-view").hidden = true;
  $("main-view").hidden = false;
  $("footer").hidden = false;
  $("account").textContent = cfg.email;
  try {
    page = await readActiveTab();
  } catch (e) {
    page = null;
    $("page-title").textContent = "无法读取当前页面";
    $("page-url").textContent = "";
    setStatus(e.message, "error");
    $("save").disabled = $("subscribe").disabled = true;
    return;
  }
  $("page-title").textContent = page.title;
  $("page-url").textContent = page.url;
  $("page-note").textContent = page.selection
    ? `已选中 ${page.selection.length} 字，保存时只存选中部分`
    : page.text
      ? `正文约 ${page.text.length} 字`
      : "读取不到正文，只保存标题和网址";
  $("feed-choice").hidden = page.feeds.length === 0;
}

async function onLogin() {
  busy(true);
  setStatus("");
  try {
    const server = normalizeServer($("server").value);
    // 只对这一个服务器申请访问权限（必须在点击事件里申请）
    const granted = await chrome.permissions.request({ origins: [server + "/*"] });
    if (!granted) throw new Error("需要允许插件访问拾课服务器");
    cfg.server = server;
    cfg.token = "";
    const data = await api("/api/auth/login", { email: $("email").value.trim(), password: $("password").value });
    $("password").value = "";
    await saveConfig({ server, token: data.token, email: data.user?.email || $("email").value.trim() });
    await showMain();
  } catch (e) {
    setStatus(e.message, "error");
  } finally {
    busy(false);
  }
}

async function handleAuth(e) {
  if (e instanceof ApiError && e.status === 401) {
    await saveConfig({ token: "" });
    showLogin();
    setStatus("登录已过期，请重新登录", "error");
    return true;
  }
  return false;
}

async function onSave() {
  if (!page) return;
  busy(true);
  setStatus("正在保存…");
  try {
    const r = await api("/api/clips", { url: page.url, title: page.title, text: page.selection || page.text });
    const msg = {
      new: "已保存到收件箱",
      changed: "页面有变化，已记录新版本",
      merged: "已合并到收件箱里的同一事项",
      unchanged: "内容没有变化，收件箱里已有这条",
    }[r.status];
    setStatus(msg || "已保存", "ok");
  } catch (e) {
    if (!(await handleAuth(e))) setStatus(e.message, "error");
  } finally {
    busy(false);
  }
}

async function onSubscribe() {
  if (!page) return;
  busy(true);
  setStatus("正在订阅…");
  const useRss = page.feeds.length > 0 && document.querySelector('input[name="sub"]:checked')?.value === "rss";
  const body = useRss
    ? { type: "rss", endpoint: page.feeds[0].href, name: (page.feeds[0].title || page.title).slice(0, 60) }
    : { type: "web", endpoint: page.url, name: page.title.slice(0, 60), config: { mode: "page" } };
  try {
    await api("/api/sources", body);
    setStatus(useRss ? "已订阅 RSS，有新内容会推送给你" : "已订阅，页面内容变化时会推送给你", "ok");
  } catch (e) {
    if (!(await handleAuth(e))) setStatus(e.message, "error");
  } finally {
    busy(false);
  }
}

async function onLogout(ev) {
  ev.preventDefault();
  await saveConfig({ token: "" });
  showLogin();
  setStatus("已退出");
}

function onOpen(ev) {
  ev.preventDefault();
  chrome.tabs.create({ url: cfg.server + "/" });
}

document.addEventListener("DOMContentLoaded", async () => {
  $("login").addEventListener("click", onLogin);
  $("password").addEventListener("keydown", (e) => e.key === "Enter" && onLogin());
  $("save").addEventListener("click", onSave);
  $("subscribe").addEventListener("click", onSubscribe);
  $("logout").addEventListener("click", onLogout);
  $("open").addEventListener("click", onOpen);
  await loadConfig();
  if (cfg.server && cfg.token) await showMain();
  else showLogin();
});
