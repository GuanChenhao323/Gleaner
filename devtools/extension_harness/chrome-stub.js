// Historical 0.1 popup stub only; current worker tests live in extension/tests/.
// 测试替身：在普通网页里模拟插件运行环境（chrome.storage / permissions / tabs / scripting）
(() => {
  const TARGET = "http://localhost:8090/news/1.html";
  const SAMPLE = `<html><head><title>学术讲座：网络协议设计</title>
    <link rel="alternate" type="application/rss+xml" title="学院新闻 RSS" href="http://localhost:8090/news/rss.xml"></head>
    <body><nav>首页 | 新闻 | 通知</nav><main><h1>学术讲座：网络协议设计</h1>
    <p>时间：2026年11月5日 14:00，地点：A101。</p><p>报名截止：2026年11月3日 23:59。</p></main>
    <footer>版权所有</footer></body></html>`;
  const frame = document.createElement("iframe");
  frame.style.display = "none";
  frame.srcdoc = SAMPLE;
  const ready = new Promise((r) => (frame.onload = r));
  document.documentElement.appendChild(frame);
  const store = JSON.parse(localStorage.getItem("ext") || "{}");
  window.__calls = [];
  window.chrome = {
    storage: { local: {
      get: async (keys) => Object.fromEntries(keys.filter((k) => k in store).map((k) => [k, store[k]])),
      set: async (obj) => { Object.assign(store, obj); localStorage.setItem("ext", JSON.stringify(store)); },
    } },
    permissions: { request: async (p) => { window.__calls.push(["permissions.request", p]); return true; } },
    tabs: {
      query: async () => [{ id: 1, url: TARGET, title: "学术讲座：网络协议设计" }],
      create: async (o) => window.__calls.push(["tabs.create", o]),
    },
    scripting: { executeScript: async ({ func, args }) => {
      await ready;
      const w = frame.contentWindow;
      const result = w.eval("(" + func.toString() + ")").apply(w, args);
      return [{ result: { ...result, url: TARGET } }]; // srcdoc 的 location 不是真实网址
    } },
  };
})();
