# 多语言（默认英文）

- 标题固定为 **拾课 Gleaner**（`appTitle` / `web/index.html` / `manifest.json`）
- `flutter gen-l10n`：`lib/l10n/app_en.arb` / `app_zh.arb` / `app_zh_TW.arb`
- `localeProvider` 持久化到 SharedPreferences，默认 `en`
- 设置页可选 English / 简体中文 / 繁體中文
- 收件箱 UI chrome 与演示种子数据（fake_moodle / templates）默认英文；切换中文时 UI 变中文，事项正文仍为源内容语言

- favicon / PWA icons 换成 assets/logo.png 的黄色 G
- Courses / Sources 列表页可见 chrome 接 l10n（待完成、采集按钮、指标卡、空状态、已删除/旧资料区）
- change_note / score reasons / 监测失败原因 / 来源 toast 在英文 locale 下本地化
- 全局审查：Settings/Transfer/Courses detail/Purge 接 l10n；Sources 深层页与 api/store 硬编码中文改为英文（品牌名「拾课」保留）；简体/繁体对深层 Sources 页尚未全部回迁 l10n
