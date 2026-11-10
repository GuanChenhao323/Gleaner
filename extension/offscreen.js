// offscreen 文档：把后台重新获取的 HTML 解析成 DOM，用与弹窗相同的规则识别候选事项。
// 解析出的文档不执行脚本（DOMParser 生成的文档是惰性的），也不加载图片等子资源。

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.target !== "offscreen" || msg.type !== "parse") return false;
  try {
    const doc = new DOMParser().parseFromString(msg.html, "text/html");
    // 相对链接按最终地址解析（可能经过重定向）
    const base = doc.createElement("base");
    base.href = msg.finalUrl;
    doc.head.prepend(base);
    const login = globalThis.gleanerCandidates.looksLikeLogin(doc, msg.finalUrl);
    const result = globalThis.gleanerCandidates.extract(doc, msg.pageUrl);
    reply({ login, result });
  } catch (e) {
    reply({ error: String(e) });
  }
  return false;
});
