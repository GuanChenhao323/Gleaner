# 浏览器和本地后端交接验收

本地控制面通过 `GLEANER_LOCAL_PAGE_PORT` 显式启用，`GLEANER_LOCAL_EXTENSION_ID` 绑定安装的扩展。插件查询已保存的 Moodle 作业来源，在打开的原页核对账号后关联本地服务。控制监听绑定 127.0.0.1，工作台签发有效期 20 秒、限一个用户、来源和操作的一次性票据。关联来源后须已有明确供应给本地服务的站点会话才可接手。插件的关联操作不会从 Chrome 导出登录凭证。

浏览器心跳报告来源页面的存在状态。匹配页面在场时由浏览器领取任务。明确关闭后，或者设备心跳过期且本地已经取得对应授权会话时，本地后端使用同一个来源租约。首版协议提取支持注册范围内的 MUST Moodle 作业详情。后台从实际 HTML 再次核对账号、活动编号和采集条件。页面无法与既有浏览器快照比较时保留旧记录。

通过 `.venv/bin/python -m pytest -q server/tests/test_local_page_host.py server/tests/test_resident_monitoring.py` 验证无凭证等待、交接、账号不符、缺失正文、恢复浏览器领取以及一次性票据。业务服务、SQLite、PageMonitor 和验证逻辑均实际运行。上游响应与凭证使用合成样本，真实已登录网站的协议交接尚未验证。常规 Chrome Dashboard 的登录状态不能单独证明端到端交接成功。
