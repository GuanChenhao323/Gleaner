# 慢站隔离开发验证

调度器接受受信的单站 Registry、transport、adapter 和 outbox。每个来源沿用原检查 ID、版本和认证代次。每站使用独立的 SQLite 文件，因此旧的主机冷却和账号轮次键仍归属于原站。对照实验两侧采用相同的磁盘布局。可以将多个 origin 配到同一组，共享在途数、网络起始间隔和冷却。

运行 `.venv/bin/python -m pytest -q server/tests/test_monitoring_scheduler.py` 验证慢请求期间其他站点完成交付、占用中的认证锁不消耗全局名额，以及同组冷却到期后自行恢复。全局默认 8 个检查，同站最多 1 个。生产协议读取继续使用明确登记的站点范围。

复现实验使用下列命令。采样阶段匿名读取公开网址，Moodle 始终使用与真实活动 ID 对应的合成页面。计时只访问回环地址。

```sh
.venv/bin/python -m devtools.monitoring.isolation_replay outputs/monitoring-isolation
.venv/bin/python -m devtools.monitoring.isolation_benchmark --corpus outputs/monitoring-isolation/corpus --output outputs/monitoring-isolation/paired.jsonl
.venv/bin/python -m devtools.monitoring.isolation_report outputs/monitoring-isolation/paired.jsonl --output outputs/monitoring-isolation/paired-summary.json
```

本次冻结 93 个公开网页，另外 7 页分别因站点策略阻止（3）、robots 禁止（2）、内容不适合回放（2）采用带明确标记的替代页。另有 60 个合成作业页面。每次回放校验文件 SHA-256，落盘时核对预期标题。每轮使用独立的调度进程和独立的 HTTP 回放进程。快速回归的两组场景、两种策略、两种延迟共 8 轮全部完成，每轮落盘 100 页，回放端单站在途峰值均为 1。快速回归缩短等待时间，不作为正式性能结论。

正式运行使用 `--scale 1`（默认值），每个条件 20 轮。结果包括固定分母分位数、截止时未完成数、CPU、独立采样的 RSS、有效正文 Mbps、分用途 HTTP 请求数和两端时序。额外机制对照使用 `--mechanisms`。本开发记录不预填性能结论。
