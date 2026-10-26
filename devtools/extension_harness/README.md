# 插件弹窗测试页

内置浏览器和自动化测试无法加载真正的浏览器插件，这里用 `chrome-stub.js` 模拟 `chrome.storage / permissions / tabs / scripting`，
直接加载 `extension/` 里的真实 `popup.js`，在普通网页里走一遍“登录 → 保存到收件箱 → 订阅更新”。

```bash
python devtools/dev_all.py --seed                              # 开发环境允许跨域（GLEANER_CORS_ORIGINS=*）
python -m http.server 8097 --bind 127.0.0.1                    # 在仓库根目录运行
# 浏览器打开 http://127.0.0.1:8097/devtools/extension_harness/popup.html
# 服务器 http://localhost:8080，账号 demo@gleaner.test / demo12345
```

模拟的“当前页面”是 `chrome-stub.js` 里的示例 HTML（带 RSS 链接与截止时间），网址指向 fake_moodle 的 `/news/1.html`，
订阅时服务端会真的去抓这个地址。真实插件请按 `docs/browser-extension.md` 第 4 节加载 `extension/` 目录。
