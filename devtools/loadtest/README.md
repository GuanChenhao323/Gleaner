# 压测与对比实验

| 脚本 | 对应 proposal 实验 |
| --- | --- |
| `ws_load.py` | 单推送节点 ≥ 5000 并发连接；单节点与三节点对比（实验 5） |
| `select_vs_epoll.py` | 实验 1 的最小对照：独立回显服务器上的 select 与 epoll |
| `mqtt_load.py` | 实验 4：QoS 0 与 QoS 1 吞吐、丢包下的送达率 |

实验 2（连接池与 keep-alive）、实验 3（条件请求）的数据来自采集引擎自身的指标：
`gleaner_fetch_total{status="304"}`、`sources.stats.totals`（每个来源的请求数、304 数、字节数），
以及 `HTTPClient.stats`（`connections_opened` / `connections_reused`）。

丢包与延迟注入（Linux）：

```bash
sudo tc qdisc add dev lo root netem delay 50ms 10ms loss 5%
sudo tc qdisc del dev lo root
```

压测前提高文件描述符上限：`ulimit -n 65535`。`ws_load.py` 会批量注册账号，压测环境需设置 `GLEANER_REQUIRE_EMAIL_CODE=0`、`GLEANER_TRUST_PROXY=1`（按 X-Forwarded-For 区分 IP 限流）。

## 实验 1：推送节点 select 与 epoll

推送节点默认使用手写反应器，可直接切换多路复用实现做对比（Linux）：

```bash
GLEANER_PUSH_SELECTOR=select python -m gleaner push    # select 受 FD_SETSIZE=1024 限制
GLEANER_PUSH_SELECTOR=epoll  python -m gleaner push
python devtools/loadtest/ws_load.py --users 5000 --ramp 500
```

`/health` 会返回当前使用的 selector；CPU 用 `pidstat -p <pid> 1` 采集。
