# Chrome API 模拟测试入口

2026-11-05：旧 0.1 popup 的普通网页测试页停止使用。0.2 的 popup 通过真正的 MV3 worker 提交任务；普通网页不能冒充该运行环境。`chrome-stub.js` 保留作历史参考，不再注入当前 popup。

当前可自动运行的替代入口：

```bash
npm --prefix extension ci
npm --prefix extension test
```

- `extension/tests/capture.test.js`：在合成 DOM 中执行真实内容运行时／适配器，检查同页候选、课表上下文、登录／选区／加载壳、严格响应和 outbox。
- `extension/tests/worker.test.js`：用模拟 Chrome API 执行真实 background 模块，覆盖持久意图、popup 丢失、worker 重建、已提交但响应丢失重放、租约中断及自有标签清理。

这些结果只能标为 **模拟 DOM／Chrome API 测试**，不能证明真实 Chrome 权限、Cookie、alarm 或真实学校 DOM 已通过验收。

真实 Chrome 手动验收使用 [三来源结构夹具](../campus_fixture/README.md)，按 [插件说明](../../docs/browser-extension.md) 加载 `extension/`。学校真实页面另按访问登记和用户本人登录验证。
