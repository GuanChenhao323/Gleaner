# 压测与对比实验

| 脚本 | 对应 proposal 实验 |
| --- | --- |
| `ws_load.py` | 单推送节点 ≥ 5000 并发连接；单节点与三节点对比（实验 5） |
| `select_vs_epoll.py` | 实验 1 的最小对照：独立回显服务器上的 select 与 epoll |
| `mqtt_load.py` | 实验 4：QoS 0 与 QoS 1 吞吐、丢包下的送达率 |
| `cluster.py` | 本机多进程集群（业务、N 个推送节点、网关各一个进程），没有 Docker 时代替 compose |
| `push_bench.py` | `capacity`：单节点 5000 连接与推送延迟；`selector`：实验 1；`scale`：实验 5 |
| `experiments.py` | `keepalive` 实验 2、`conditional` 实验 3、`mqtt` / `mqtt-chaos` 实验 4、`rest` 网关吞吐 |
| `rest_workers.py` | 网关 1 个与 4 个 worker 的吞吐对比（Linux，压测端多进程） |
| `../autobahn_lite.py` | 精简版 WebSocket 一致性测试（38 个用例，两套实现） |
| `../check_compose.py` | docker-compose 静态检查 |

结果统一写入 `docs/evaluation/results/`（Linux 上文件名自动加 `_linux`），汇总见 `docs/evaluation/README.md`。

实验 2（连接池与 keep-alive）、实验 3（条件请求）的数据来自采集引擎自身的指标：
`gleaner_fetch_total{status="304"}`、`sources.stats.totals`（每个来源的请求数、304 数、字节数），
以及 `HTTPClient.stats`（`connections_opened` / `connections_reused`）。

丢包与延迟注入（Linux）：

```bash
sudo tc qdisc add dev lo root netem delay 50ms 10ms loss 5%
sudo tc qdisc del dev lo root
```

压测前提高文件描述符上限：`ulimit -n 65535`。

WSL 2（镜像网络）上额外注意：

- 先 `unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy`，否则 requests / websockets 会把 localhost 请求发给代理。
- 临时端口只有 4096 个，经网关建不出 5000 条连接，用 `push_bench.py capacity --users 5000 --direct` 直连推送节点。
- 发往 127.0.0.1 的流量经 Windows 回环，`lo` 上的 netem 无效；丢包实验用 `GLEANER_BENCH_HOST=127.0.0.2`：

```bash
sudo tc qdisc add dev lo root netem delay 50ms 10ms loss 5%
GLEANER_BENCH_HOST=127.0.0.2 python devtools/loadtest/experiments.py mqtt --subs 10 --messages 500 --rate 50 --netem "delay 50ms 10ms loss 5%"
sudo tc qdisc del dev lo root
````ws_load.py` 会批量注册账号，压测环境需设置 `GLEANER_REQUIRE_EMAIL_CODE=0`、`GLEANER_TRUST_PROXY=1`（按 X-Forwarded-For 区分 IP 限流）。

## 实验 1：推送节点 select 与 epoll

推送节点默认使用手写反应器，可直接切换多路复用实现做对比（Linux）：

```bash
GLEANER_PUSH_SELECTOR=select python -m gleaner push    # select 受 FD_SETSIZE=1024 限制
GLEANER_PUSH_SELECTOR=epoll  python -m gleaner push
python devtools/loadtest/ws_load.py --users 5000 --ramp 500
```

`/health` 会返回当前使用的 selector；CPU 用 `pidstat -p <pid> 1` 采集。
