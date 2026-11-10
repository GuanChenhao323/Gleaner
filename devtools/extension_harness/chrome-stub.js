// 测试替身：在普通网页里模拟插件运行环境（chrome.storage / permissions / tabs / scripting / runtime）
// 用 ?sample=moodle（默认）或 ?sample=news 选择模拟的“当前页面”。
(() => {
  const SAMPLES = {
    // 与 devtools/fake_moodle 的作业列表页结构相同（/mod/assign/index.php）
    moodle: {
      url: "http://localhost:8090/mod/assign/index.php?id=1",
      title: "Assignments",
      html: `<!DOCTYPE html><html><head><title>Assignments</title></head><body id="page-site">
        <header><a href="/my/" class="navbar-brand">Fake Moodle</a></header>
        <main id="region-main" role="main"><h2>Assignments</h2>
        <table class="generaltable mod_index"><thead><tr><th>Topic</th><th>Assignments</th><th>Due date</th></tr></thead><tbody>
        <tr><td>Topic 1</td><td><a href="/mod/assign/view.php?id=11">Lab 1: socket programming</a></td><td>Friday, 13 November 2026, 11:59 PM</td></tr>
        <tr><td>Topic 2</td><td><a href="/mod/assign/view.php?id=12">Lab 2: HTTP server</a></td><td>Friday, 20 November 2026, 11:59 PM</td></tr>
        <tr><td>Topic 3</td><td><a href="/mod/forum/discuss.php?d=7">课程调整通知</a></td><td></td></tr>
        </tbody></table></main></body></html>`,
    },
    news: {
      url: "http://localhost:8090/news/",
      title: "学院通知",
      html: `<html><head><title>学院通知</title>
        <link rel="alternate" type="application/rss+xml" title="学院新闻 RSS" href="/news/rss.xml"></head>
        <body><nav><a href="/">首页</a> | <a href="/news/">新闻</a></nav><main><h1>学院通知</h1><ul>
        <li><a href="/news/1.html">学术讲座：网络协议设计</a> 时间：2026年11月12日 14:00，地点：A101</li>
        <li><a href="/news/2.html">期中考试安排</a> 2026年11月18日 9:00 在 B203 考试</li>
        <li><a href="/news/3.html">教学楼停电通知</a> 本周六全天停电</li>
        </ul></main><footer>版权所有</footer></body></html>`,
    },
  };
  const sample = SAMPLES[new URLSearchParams(location.search).get("sample") || "moodle"] || SAMPLES.moodle;
  const frame = document.createElement("iframe");
  frame.style.display = "none";
  // 用 <base> 让相对链接按模拟网址解析（srcdoc 的 location 不是真实网址）
  frame.srcdoc = sample.html.replace(/<head>/i, `<head><base href="${sample.url}">`);
  const ready = new Promise((r) => (frame.onload = r));
  document.documentElement.appendChild(frame);
  const store = JSON.parse(localStorage.getItem("ext") || "{}");
  window.__calls = [];
  window.chrome = {
    storage: {
      local: {
        get: async (keys) => Object.fromEntries(keys.filter((k) => k in store).map((k) => [k, store[k]])),
        set: async (obj) => {
          Object.assign(store, obj);
          localStorage.setItem("ext", JSON.stringify(store));
        },
      },
    },
    permissions: {
      request: async (p) => {
        window.__calls.push(["permissions.request", p]);
        return true;
      },
      contains: async () => true,
    },
    runtime: { sendMessage: async (m) => window.__calls.push(["runtime.sendMessage", m]) },
    tabs: {
      query: async () => [{ id: 1, url: sample.url, title: sample.title }],
      create: async (o) => window.__calls.push(["tabs.create", o]),
    },
    scripting: {
      executeScript: async ({ func, args, files }) => {
        await ready;
        const w = frame.contentWindow;
        if (files) {
          for (const f of files) w.eval(await (await fetch("../../extension/" + f)).text());
          return [{ result: undefined }];
        }
        // 页面里的 location.href 是 about:srcdoc：换成模拟网址再执行
        const src = "(" + func.toString().replaceAll("location.href", JSON.stringify(sample.url)) + ")";
        return [{ result: w.eval(src).apply(w, args) }];
      },
    },
  };
})();
