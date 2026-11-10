# 插件弹窗测试页

内置浏览器和自动化测试无法加载真正的浏览器插件，这里用 `chrome-stub.js` 模拟 `chrome.storage / permissions / tabs / scripting`，
直接加载 `extension/` 里的真实 `candidates.js` 与 `popup.js`，在普通网页里走一遍“登录 → 识别候选事项 → 勾选并批量保存 → 逐条结果”。
后台监测（`background.js`、offscreen 文档）依赖真实的扩展环境，测试页不覆盖。

```bash
python devtools/dev_all.py --seed                              # 开发环境放行本机来源（http://127.0.0.1:*）
python -m http.server 8097 --bind 127.0.0.1                    # 在仓库根目录运行
# 浏览器打开 http://127.0.0.1:8097/devtools/extension_harness/popup.html?sample=moodle（或 ?sample=news）
# 服务器 http://localhost:8080，账号 demo@gleaner.test / demo12345
```

模拟的“当前页面”是 `chrome-stub.js` 里的两份示例 HTML：fake_moodle 结构的作业列表，以及学院通知列表（带 RSS 链接）。真实插件请按 `docs/browser-extension.md` 第 4 节加载 `extension/` 目录。
