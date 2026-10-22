# 评估结果

原始数据在 `results/*.json`（含运行环境与说明），由 `devtools/loadtest/experiments.py` 生成，可原样重跑。

## 第一轮：Windows 开发机（2026-10-22）

环境：Windows 11、Python 3.14、i9-11900H（16 线程）、64 GB 内存；服务与压测客户端同机，走本机回环。
这一轮只做不依赖 Linux 的实验；正式数据以 Linux（WSL / 云服务器）为准，见下一节。

### 实验 2：有无连接池与 keep-alive

10 个 URL × 30 轮，每主机并发 4，目标为 fake_moodle。

| 模式 | 请求数 | TCP 握手次数 | 连接复用次数 | 总耗时 s | 吞吐 req/s | P50 ms | P99 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 连接池 + keep-alive | 300 | 4 | 296 | 0.17 | 1772 | 2.88 | 8.34 |
| 每次新建连接 | 300 | 300 | 0 | 0.52 | 575 | 10.15 | 21.42 |

TCP 握手次数从 300 降到 4（等于每主机并发上限），吞吐约提高 3.1 倍，P99 延迟降低约 61%。
本机回环没有网络往返时延，到真实校园站点（RTT 数十毫秒、外加 TLS 握手）时差距会更大。

### 实验 3：有无条件请求

模拟 100 个检查周期，每 20 个周期来源发布一条新通知；每周期检查列表页、RSS、教师页与全部详情页。

| 模式 | 请求数 | 304 次数 | 304 占比 | 接收字节 KB | 节省流量 |
| --- | --- | --- | --- | --- | --- |
| 条件请求（ETag / If-Modified-Since） | 1200 | 1178 | 98.2% | 247.7 | **86.5%** |
| 无条件请求 | 1200 | 0 | 0.0% | 1831.2 | — |

达到 proposal 目标“条件请求节省的流量 ≥ 70%”。字节数包含响应头，所以 304 响应仍有少量流量。

### 实验 4：MQTT QoS 0 与 QoS 1

自研 Broker 独立进程，20 个 paho 订阅者。“突发”是一次性发布 2000 条，测吞吐；“限速”是每秒发布 100 条，测正常负载下的端到端延迟。

| 模式 | QoS | 订阅者 | 发布条数 | 送达率 | 吞吐 msg/s | P50 ms | P99 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 突发 | 0 | 20 | 2000 | 100% | 12552 | 911.5 | 1651.4 |
| 突发 | 1 | 20 | 2000 | 100% | 7400 | 2737.0 | 5295.9 |
| 限速 100 条/s | 0 | 20 | 1000 | 100% | 2000 | 1.45 | 2.42 |
| 限速 100 条/s | 1 | 20 | 1000 | 100% | 2000 | 1.84 | 3.69 |

- QoS 1 的突发吞吐约为 QoS 0 的 59%，多出的开销来自 PUBACK 往返与 inflight 窗口（每会话 20 条）。
- 突发模式的延迟主要是排队时间（2000 条同时进入队列），不代表正常负载；正常负载下 P99 只有几毫秒。
- 丢包环境下的送达率需要 Linux `tc netem`，待补。

### 网关 REST 吞吐

开发模式（`devtools/dev_all.py`：网关、业务服务等全部在**同一个 Python 进程**），64 并发，每个接口 10 秒。

| 接口 | 并发 | 请求数 | 状态码 | 吞吐 req/s | P50 ms | P99 ms |
| --- | --- | --- | --- | --- | --- | --- |
| /health（只到网关） | 64 | 51646 | 200×51646 | 5159 | 11.9 | 17.8 |
| /api/templates（网关反向代理到业务服务） | 64 | 9546 | 200×9546 | 950 | 66.5 | 75.3 |

proposal 目标是“2 核、缓存命中 ≥ 1000 req/s”。这里网关和业务服务挤在一个进程里共用一个 GIL，压测客户端也在同机，结果偏保守；
compose 部署时它们是独立进程，网关还可以 `GLEANER_WORKERS=N` 多进程（SO_REUSEPORT），待在 Linux 上复测。

## 第二轮：Linux（待安装 WSL 2 + Docker 后补）

| 项目 | 命令 | 状态 |
| --- | --- | --- |
| docker compose 演示路径 | `docker compose -f deploy/docker-compose.yml --profile dev up --build` | 待运行 |
| Autobahn 一致性测试 | `docker compose -f deploy/docker-compose.yml --profile conformance run --rm autobahn` | 待运行 |
| 实验 1：select 与 epoll（推送节点） | `GLEANER_PUSH_SELECTOR=select / epoll` + `ws_load.py` | 待运行（Windows 上 select 最多 512 个 socket，没有 epoll） |
| 单推送节点 ≥ 5000 连接、推送延迟 P99 | `ws_load.py --users 5000` | 待运行 |
| 实验 5：单节点与三节点 | compose 中扩展推送节点 | 待运行 |
| 实验 4 丢包场景 | `tc qdisc add dev lo root netem loss 5%` + `experiments.py mqtt` | 待运行 |
| 网关 REST 吞吐复测 | `experiments.py rest`（compose 多进程） | 待运行 |
