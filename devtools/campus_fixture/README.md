# 三来源合成结构夹具

这里的 HTML 为工程测试设计，**不是真实 MUST DOM 的拷贝或验证证据**，没有学校数据、私有 API 或真实凭据。仅绑定 loopback；不用于部署。

```bash
.venv/bin/python devtools/dev_all.py --seed
.venv/bin/python devtools/campus_fixture/app.py --port 8098
# 两个进程分别在独立终端运行，Ctrl+C 停止。
```

在真实 Chrome 加载仓库 `extension/`（开发者模式），连接 `http://localhost:8080`，演示账号 `demo@gleaner.test / demo12345`。打开 `http://localhost:8098/`。

| 路径 | 合成场景 |
|---|---|
| /person/id-828.html?locale=zh_MO | 三个目录候选，个人详情需先读取预览 |
| /person/view/id-9001.html?locale=zh_MO | 个人身份、部门／办公室／邮箱；全局页脚联系方式排除 |
| /capture/moodle-dashboard | 内容 aside 内的三课程卡片、两条目标作业和 Timeline；人工智能只预览入口 |
| /capture/unsupported | 未识别布局必须报错，不能返回成功零匹配 |
| /capture/courses | 三课程；输入“网络编程的作业”仅返回两条，另两课程不提取 |
| /capture/courses?ambiguous=1 | 同名课程需先确认原生课程范围 |
| /my/ | 模拟登录后课程入口和三个具体作业，课程不保存成事项 |
| /mod/assign/view.php?id=1001 | 活动 ID、日期原文和提交要求 |
| /portal#news | 同 URL 三个 native notice ID，允许只保存两条 |
| /portal#timetable | 学期／周次／星期／节次，无完整校历日期 |
| /portal?fault=shell#news | 无内容加载壳，产生有界渲染超时 |
| /admin | 增加版本、切换详情选区丢失、使模拟浏览器登录失效 |
| /login | 选择 student-a 或 student-b；账号切换不应写回旧绑定 |

当前推荐验收：打开 `/capture/moodle-dashboard` → 插件输入“人工智能”或“Timeline”查看仅预览内容 → 改为“网络编程的作业” → 两条完整预览且无逐项复选框 → 一次保存 → Flutter 回执链接打开原事项。修改管理台后重新抓取并明确保存，查看版本差异。新快照不支持自动监测；原有 v1 后台监测测试只证明兼容实现。

页面首次访问授权可能使 popup 关闭；重新打开即可。学校会话只在 Chrome 内，通过正常导航重新读取，没有发送 Cookie 到后端。使用 localhost 和 127.0.0.1 会形成不同浏览器会话／绑定，测试中请固定一个主机名。

结构和错误自动测试见 `extension/tests/`；后端契约测试见 `server/tests/test_browser_capture.py`。真实站点的路由、frame、账号标识及可重入性仍需授权样例验证。
