// Campus Radar 插件弹窗：识别当前页面的候选事项，用户勾选后批量保存到本地后端（IC-001）。
// 只在用户点开弹窗时读取当前标签页（activeTab）；只对用户填写的后端地址、以及用户同意监测的网站申请权限。

const MAX_TEXT = 100000; // 与服务端 CLIP_MAX_TEXT 一致
const MAX_ITEMS = 50; // 与服务端 CAPTURE_MAX_ITEMS 一致

const $ = (id) => document.getElementById(id);
let cfg = { server: "", token: "", email: "" };
let page = null; // { url, title, platform, candidates, page, feeds, selection }
let items = []; // 弹窗里列出的候选事项

function setStatus(text, kind = "") {
  const el = $("status");
  el.textContent = text;
  el.className = kind;
}

function busy(on) {
  for (const id of ["login", "save", "subscribe"]) $(id).disabled = on;
  if (!on) updateCount();
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
  if (u.protocol !== "http:" && u.protocol !== "https:") throw new Error("后端地址要以 http:// 或 https:// 开头");
  return u.origin;
}

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, body) {
  let res;
  try {
    res = await fetch(cfg.server + path, {
      method: body ? "POST" : "GET",
      headers: {
        "Content-Type": "application/json",
        ...(cfg.token ? { Authorization: `Bearer ${cfg.token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "连不上本地后端，请确认后端正在运行");
  }
  let data = {};
  try {
    data = await res.json();
  } catch {
    // 非 JSON 响应（例如网关 502 页面）
  }
  if (!res.ok || data.ok === false) {
    const msg = data.message || (typeof data.error === "string" ? data.error : "") || `请求失败（HTTP ${res.status}）`;
    const err = new ApiError(res.status, msg);
    err.data = data;
    throw err;
  }
  return data;
}

// 没有稳定标识时的定位符：规范化标题的 SHA-1 前 12 位（IC-001 3.1）
async function titleLocator(title) {
  const n = title.replace(/\s+/g, " ").trim().toLowerCase();
  const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(n));
  const hex = [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return "t:" + hex.slice(0, 12);
}

async function readActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https?:/i.test(tab.url || "")) {
    throw new Error("这个页面不能保存（只支持 http / https 网页）");
  }
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["candidates.js"] });
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (maxText) => {
        const r = globalThis.gleanerCandidates.extract(document, location.href, maxText);
        r.selection = String(window.getSelection() || "").trim().slice(0, maxText);
        return r;
      },
      args: [MAX_TEXT],
    });
    return res.result;
  } catch {
    // 浏览器商店、PDF 等页面不允许注入脚本：仍可保存标题和网址
    const t = tab.title || tab.url;
    return {
      url: tab.url,
      title: t,
      platform: "web",
      candidates: [],
      page: { locator: "page", title: t, text: "", url: tab.url },
      feeds: [],
      selection: "",
    };
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

function updateCount() {
  const n = items.filter((c) => c.checked).length;
  $("save").disabled = n === 0;
  $("save").textContent = n ? `保存选中的 ${n} 条` : "先勾选要保存的事项";
  $("pick-count").textContent = `识别到 ${items.length} 条，已选 ${n} 条`;
  $("pick-all").textContent = n === items.length ? "全不选" : "全选";
}

const TYPE_LABEL = { todo: "待办", event: "日程", notice: "通知" };

function renderCandidates() {
  const ul = $("candidates");
  ul.textContent = "";
  items.forEach((c, i) => {
    const li = document.createElement("li");
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = c.checked;
    box.addEventListener("change", () => {
      c.checked = box.checked;
      updateCount();
    });
    const span = document.createElement("span");
    span.className = "cand-title";
    span.textContent = c.title;
    label.append(box, span);
    if (c.type) {
      const tag = document.createElement("em");
      tag.className = "tag";
      tag.textContent = TYPE_LABEL[c.type] || c.type;
      label.append(tag);
    }
    li.append(label);
    li.dataset.index = String(i);
    ul.append(li);
  });
  $("pick").hidden = items.length === 0;
  updateCount();
}

async function showMain() {
  $("login-view").hidden = true;
  $("main-view").hidden = false;
  $("footer").hidden = false;
  $("account").textContent = cfg.email;
  $("results").hidden = true;
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
  if (page.selection) {
    // 选中了文字：只保存选中部分，作为一条事项
    const title = page.selection.split("\n")[0].slice(0, 120);
    items = [{ locator: await titleLocator(title), title, text: page.selection, url: page.url, checked: true }];
    $("page-note").textContent = `已选中 ${page.selection.length} 字，保存为一条事项（选中内容无法自动检查变化）`;
  } else if (page.candidates.length) {
    // 多条候选：默认都不勾选，由用户选择（US01：未选中的不保存）
    items = page.candidates.map((c) => ({ ...c, checked: page.candidates.length === 1 }));
    $("page-note").textContent =
      page.platform === "moodle" ? "Moodle 页面：勾选要保存的活动或讨论" : "勾选要保存的条目";
  } else {
    items = [{ ...page.page, checked: true }];
    $("page-note").textContent = page.page.text ? `整页保存，正文约 ${page.page.text.length} 字` : "读取不到正文，只保存标题和网址";
  }
  renderCandidates();
  $("feed-choice").hidden = page.feeds.length === 0;
}

async function onLogin() {
  busy(true);
  setStatus("");
  try {
    const server = normalizeServer($("server").value);
    // 只对这一个后端地址申请访问权限（必须在点击事件里申请）
    const granted = await chrome.permissions.request({ origins: [server + "/*"] });
    if (!granted) throw new Error("需要允许插件访问本地后端");
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

// 监测需要能在后台重新读取这个网站：在点击事件里申请该网站的访问权限
async function monitorPermission() {
  if (!$("monitor").checked) return false;
  const origin = new URL(page.url).origin;
  try {
    return await chrome.permissions.request({ origins: [origin + "/*"] });
  } catch {
    return false;
  }
}

const STATUS_TEXT = {
  new: "已保存",
  changed: "已更新（记录了新版本）",
  unchanged: "已保存过，内容没有变化",
};

function renderResults(results, chosen) {
  const ul = $("results");
  ul.textContent = "";
  for (const r of results) {
    const li = document.createElement("li");
    const ok = r.status !== "error";
    li.className = ok ? "ok" : "error";
    const c = chosen[r.index] || {};
    let note = ok ? STATUS_TEXT[r.status] || "已保存" : `失败：${r.error?.message || "未知错误"}`;
    if (ok && r.type) note += ` · ${TYPE_LABEL[r.type] || r.type}`;
    if (ok && r.monitor === "unsupported" && $("monitor").checked) note += " · 暂不支持自动检查";
    li.textContent = `${ok ? "✓" : "✗"} ${c.title || r.locator}：${note}`;
    ul.append(li);
  }
  ul.hidden = false;
}

async function onSave() {
  if (!page) return;
  const chosen = items.filter((c) => c.checked).slice(0, MAX_ITEMS);
  if (!chosen.length) return;
  const monitorOk = await monitorPermission(); // 必须先于其他 await，保持在用户手势内
  busy(true);
  setStatus(`正在保存 ${chosen.length} 条…`);
  try {
    const body = {
      page: { url: page.url, title: page.title, platform: page.platform },
      items: chosen.map((c) => ({
        locator: c.locator,
        title: c.title,
        text: c.text || "",
        url: c.url || page.url,
        ...(c.type ? { type: c.type } : {}),
        // 只有稳定定位符的事项才能在后台按定位符找回（标题哈希不行）
        monitor: { supported: monitorOk && !c.locator.startsWith("t:") },
      })),
    };
    const r = await api("/api/captures", body);
    renderResults(r.results, chosen);
    if (r.ok) setStatus(`已保存 ${r.saved} 条`, "ok");
    else setStatus(`保存了 ${r.saved} 条，${r.failed} 条失败`, "error");
    if (monitorOk) chrome.runtime?.sendMessage?.({ type: "monitor-kick" })?.catch?.(() => {});
  } catch (e) {
    // 后端不可用或整批被拒绝：明确报失败，不显示成功（US02）
    if (!(await handleAuth(e))) setStatus(`保存失败：${e.message}`, "error");
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
    setStatus(useRss ? "已订阅 RSS" : "已订阅，页面内容变化时会提示你", "ok");
  } catch (e) {
    if (!(await handleAuth(e))) setStatus(e.message, "error");
  } finally {
    busy(false);
  }
}

function onPickAll(ev) {
  ev.preventDefault();
  const all = items.every((c) => c.checked);
  items.forEach((c) => (c.checked = !all));
  renderCandidates();
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
  $("pick-all").addEventListener("click", onPickAll);
  $("logout").addEventListener("click", onLogout);
  $("open").addEventListener("click", onOpen);
  await loadConfig();
  if (cfg.server && cfg.token) await showMain();
  else showLogin();
});
