# 评估结果

评估目标和实验编号见 [原提案](../archive/proposal-2026-10-21.md)。

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
- 丢包环境下的结果见第二轮“tc netem 丢包”。

### 网关 REST 吞吐

开发模式（`devtools/dev_all.py`：网关、业务服务等全部在**同一个 Python 进程**），64 并发，每个接口 10 秒。

| 接口 | 并发 | 请求数 | 状态码 | 吞吐 req/s | P50 ms | P99 ms |
| --- | --- | --- | --- | --- | --- | --- |
| /health（只到网关） | 64 | 51646 | 200×51646 | 5159 | 11.9 | 17.8 |
| /api/templates（网关反向代理到业务服务） | 64 | 9546 | 200×9546 | 950 | 66.5 | 75.3 |

proposal 目标是“2 核、缓存命中 ≥ 1000 req/s”。这里网关和业务服务挤在一个进程里共用一个 GIL，压测客户端也在同机，结果偏保守；
compose 部署时它们是独立进程，网关还可以 `GLEANER_WORKERS=N` 多进程（SO_REUSEPORT），Linux 数据见第二轮。

## 第一轮补充：本机多进程集群（2026-10-22）

`devtools/loadtest/cluster.py` 把业务服务（含总线 Hub）、推送节点、网关各开成独立进程，结构与 compose 相同，只是不在容器里。
压测客户端 `push_bench.py` 经网关建立 WebSocket 连接（每个连接用不同的 X-Forwarded-For，避免同一 IP 被限流），
然后从总线发布带时间戳的消息。**延迟口径**：总线发布 → 客户端收到，不含业务服务写库。

### 单推送节点 5000 连接与推送延迟（含一次优化）

Windows 上推送节点用 asyncio（IOCP）接入；手写反应器在 Windows 只能用 select，最多 512 个 socket；5000 连接的反应器（epoll）数据见第二轮。
每秒随机向 200 个用户推送，持续 20 秒；最后向全部 5000 个在线用户各推一条（“全员扇出”）。

| 版本 | 成功连接 | 失败 | 推送 P50 ms | 推送 P99 ms | 送达 | 全员扇出耗时 s | 推送节点 CPU % | 推送节点内存 MB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 优化前 | 5000 | 0 | 4.91 | 21.65 | 4000/4000 | 8.11 | 57.6 | 480 |
| 优化后 | 5000 | 0 | **1.85** | **20.91** | 4000/4000 | **1.57** | **19.4** | 480 |

- 达到 proposal 目标：单推送节点 ≥ 5000 并发连接，推送延迟 P99 < 1 秒。
- **压测发现的瓶颈**：推送节点为每个在线用户订阅 `u.<uid>`，总线 Hub 与节点按订阅模式线性匹配，
  5000 人在线时每条消息要比较 5000 次，全员扇出约 2500 万次比较。改为精确主题哈希查找、只有通配符模式才线性匹配（`net/bus/node.py: TopicSet`）后，
  扇出耗时降为 1/5，CPU 降为 1/3。原始数据：`results/push_capacity_before_opt.json`、`results/push_capacity.json`。

### 实验 1（初步）：select 与 IOCP

Windows 上没有 epoll，先用手写反应器的 select 与 asyncio 的 IOCP 对比；规模受 select 的 512 上限限制。

| 实现 | 连接数 | 推送 P50 ms | 推送 P99 ms | 全员扇出 s | 推送节点 CPU % | 内存 MB |
| --- | --- | --- | --- | --- | --- | --- |
| select（手写反应器） | 100 | 2.04 | 4.17 | 0.11 | 16.1 | 51.7 |
| IOCP（asyncio） | 100 | 1.97 | 3.78 | 0.06 | 10.0 | 59.3 |
| select（手写反应器） | 200 | 2.38 | 4.47 | 0.11 | 20.2 | 53.1 |
| IOCP（asyncio） | 200 | 2.36 | 3.86 | 0.11 | 13.3 | 67.9 |
| select（手写反应器） | 400 | 2.26 | 4.62 | 0.21 | 19.0 | 56.0 |
| IOCP（asyncio） | 400 | 2.59 | 3.99 | 0.17 | 17.1 | 84.8 |

400 连接以内两者差距很小（select 的 CPU 高 2–6 个百分点，P99 延迟高约 0.5 ms；内存反而更省）。select 每轮扫描全部连接的 O(n) 代价要到上千连接才明显，
500 → 5000 连接的 select / epoll 曲线见第二轮。

### 实验 5（初步）：单节点与三节点

3000 个连接，每秒 200 条推送。三个节点是同一台机器上的三个进程，所以这里主要验证一致性哈希的分布与负载分摊，而不是跨机器扩容。

| 推送节点 | 节点分布 | 推送 P50 ms | 推送 P99 ms | 全员扇出 s | CPU %（合计） | 内存 MB（合计） |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | push-1:3000 | 1.69 | 3.55 | 1.01 | 14.1 | 308 |
| 3 | 995 / 954 / 1051 | 1.62 | 3.29 | 0.59 | 15.3 | 407 |

一致性哈希（每节点 160 个虚拟节点）把连接分得很均匀，节点间相差不超过 ±5%；全员扇出耗时降低 42%。

### 网关 REST 吞吐（多进程）

| 部署 | 接口 | 吞吐 req/s | P50 ms | P99 ms |
| --- | --- | --- | --- | --- |
| 单进程（dev_all） | /api/templates | 950 | 66.5 | 75.3 |
| 多进程（网关、业务服务分开） | /api/templates | **1334** | 47.3 | 62.6 |

多进程部署达到“≥ 1000 req/s”的目标（Windows 不支持 fork，网关仍是单进程；Linux 上可再开 `GLEANER_WORKERS`）。

### 实验 4 补充：网络中断场景（代替丢包注入）

Windows 没有 `tc netem`，改用故障注入 TCP 代理：订阅端经代理连接 Broker，代理每 6 秒掐断全部连接，并在 2 秒内拒绝重连（模拟手机网络中断）；发布端直连 Broker，每秒 20 条，持续 30 秒，共 10 个订阅者。

| QoS | 网络中断次数 | 送达（去重后） | 送达率 | 重复投递 |
| --- | --- | --- | --- | --- |
| 0 | 6 | 3299/6000 | 54.98% | 0 |
| 1（持久会话） | 6 | 6000/6000 | **100%** | 10 |

QoS 1 加持久会话在断线期间把消息存进离线队列，重连后补发，零丢失；代价是会出现少量重复（带 DUP 标志的重发），客户端必须按消息去重。
真正的随机丢包会被 TCP 重传掩盖，对 MQTT 来说“连接中断”才是 QoS 差异的主要来源。tc netem 丢包数据见第二轮。

### WebSocket 一致性（精简版，代替 Autobahn）

`devtools/autobahn_lite.py` 用原始 socket 手工构造帧，覆盖 Autobahn 第 1–7 类的 38 个代表性用例（长度编码、分段到达、ping/pong、RSV 位、保留 opcode、分片、
UTF-8 校验与快速失败、关闭码），对两套实现各跑一遍：

| 实现 | 结果 |
| --- | --- |
| asyncio（`websocket_route`，网关等使用） | 38/38 OK |
| 手写反应器（推送节点使用） | 36/36 OK（2 个二进制回显用例不适用：推送节点只用文本帧） |

逐条结果在 `results/autobahn_lite.json`。正式的 Autobahn Testsuite（500+ 用例）需要 Docker，待补。

### compose 静态检查

`devtools/check_compose.py` 检查构建路径、COPY 源、depends_on、服务间上游地址与端口、Prometheus 抓取目标、挂载文件。
首次运行发现并修复了 3 个问题：网关缺少 `GLEANER_MQTT_WS_UPSTREAM`（`/mqtt` 会转发回网关自己）、Prometheus 抓 Broker 的端口写错（9101 → 8083）、
Autobahn 报告目录缺失。现在 18 项检查全部通过。注意 `server/Dockerfile` 会复制 `client/build/web`，构建镜像前要先构建 Flutter Web。

## 第二轮：Linux（WSL 2，2026-10-22）

环境：同一台机器上的 WSL 2（Ubuntu 26.04、内核 6.18、Python 3.14.4、16 线程、31 GB 内存，镜像网络模式），服务与压测客户端同机。
服务端测试在 Linux 上同样 148 项全部通过。原始数据是 `results/*_linux.json`。

**WSL 2 镜像网络的三个坑**（会直接影响数据，复现时注意）：

1. 临时端口只有 4096 个（`ip_local_port_range = 44620 48715`）。经网关建 5000 条连接时，网关到推送节点这一跳只有一个目的地址，
   第 4097 条起报 `EADDRNOTAVAIL`。所以 5000 连接改用 `push_bench.py capacity --direct`：绕过网关直连推送节点，轮流连 127.0.0.1–4（每个目的地址各有一份端口空间）。
2. 发往 127.0.0.1 的 TCP/UDP 会被策略路由（`ip rule` 表 127）到 `loopback0`，经 Windows 主机绕一圈再回来，`lo` 上的 tc netem 对它无效。
   丢包实验与 REST 吞吐改走 127.0.0.2（真正的 `lo`），由 `GLEANER_BENCH_HOST` 控制。下面推送类实验仍走 127.0.0.1，select 与 epoll 两边条件一致。
3. WSL 里设置了系统代理环境变量，requests / websockets 会把 localhost 请求也发给代理，跑测试和压测前要 `unset HTTP_PROXY HTTPS_PROXY`。

### 实验 1：select 与 epoll（手写反应器）

经网关建连，每秒 200 条推送，持续 15 秒。

| 多路复用 | 连接数 | 推送 P50 ms | 推送 P99 ms | 全员扇出 s | 推送节点 CPU % | 内存 MB |
| --- | --- | --- | --- | --- | --- | --- |
| select | 250 | 1.66 | 2.29 | 0.10 | 9.7 | 55.4 |
| epoll | 250 | 1.65 | 2.23 | 0.11 | 8.3 | 55.3 |
| select | 500 | 1.79 | 2.64 | 0.16 | 12.5 | 58.5 |
| epoll | 500 | 1.70 | 2.55 | 0.16 | 9.1 | 58.2 |
| select | 900 | 1.96 | 2.71 | 0.27 | **16.9** | 63.6 |
| epoll | 900 | 1.71 | 2.51 | 0.29 | **9.8** | 63.5 |
| select | ≥ 1024 | — | — | — | — | — |
| epoll | 2000 | 1.73 | 2.45 | 0.65 | 12.3 | 76.1 |
| epoll | 5000（直连） | 1.40 | 2.13 | 1.54 | 17.5 | 110.2 |

- select 每次调用都要把全部 fd 拷进内核并线性扫描，CPU 随连接数增长：250 → 900 连接从 9.7% 涨到 16.9%（+74%）；
  epoll 只返回就绪的 fd，同样区间只从 8.3% 涨到 9.8%，到 2000 连接也才 12.3%。
- select 受 `FD_SETSIZE = 1024` 限制，文件描述符编号超过 1023 时 `select()` 直接报错，900 连接以上无法测试；epoll 到 5000 连接没有这个限制。
- 推送延迟差别不大（P99 都在 2–3 ms）：每秒 200 条的负载下瓶颈不在多路复用，差距主要体现在 CPU 与规模上限。
- 5000 那一行来自下面的容量实验（直连），其余经网关。

### 手写反应器 5000 连接

`push_bench.py capacity --users 5000 --direct`，每秒 200 条推送，持续 15 秒，最后全员扇出。

| 推送节点实现 | 成功连接 | 失败 | 握手 P99 ms | 推送 P50 ms | 推送 P99 ms | 送达 | 全员扇出 s | CPU % | 内存 MB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| asyncio（标准库 epoll 事件循环） | 5000 | 0 | 1153 | 1.15 | 1.89 | 3000/3000 | 0.64 | 9.5 | 166.1 |
| 手写反应器（epoll） | 5000 | 0 | **415** | 1.40 | 2.13 | 3000/3000 | 1.54 | 17.5 | **110.2** |

- 手写反应器达到 proposal 目标：单节点 ≥ 5000 并发连接，推送 P99 < 1 秒（实际 2.13 ms）。
- 手写反应器内存少 34%，建连握手 P99 也更低。推测原因（未做剖析验证）：每连接只有一个 `_Conn` 对象和字节缓冲，没有 asyncio 的 Transport / Protocol / StreamReader / Task；
  握手在反应器线程里同步完成，不经过任务调度。
- 全员扇出慢一些、CPU 高一些。推测原因（未做剖析验证）：消息从 asyncio（总线客户端）交给反应器线程要经过 `call_soon_threadsafe` 队列与唤醒 socket，
  并且帧编码在 Python 层逐连接进行。可优化方向：按批次跨线程投递、扇出时复用同一份编码好的帧。

### 实验 5：单节点与三节点（Linux，手写反应器）

| 推送节点 | 节点分布 | 推送 P50 ms | 推送 P99 ms | 全员扇出 s | CPU %（合计） | 内存 MB（合计） |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | push-1:3000 | 1.64 | 2.28 | 0.98 | 14.2 | 88.1 |
| 3 | 995 / 954 / 1051 | 1.72 | 2.35 | **0.42** | 16.7 | 190.9 |

三节点全员扇出耗时降低 57%（Windows 初测为 42%）。仍是单机多进程，跨机器扩容待云服务器。

### 实验 4：tc netem 丢包

回环网卡 `tc qdisc add dev lo root netem delay 50ms 10ms loss 5%`，10 个订阅者，突发 500 条 / 限速每秒 50 条，走 127.0.0.2。

| 模式 | QoS | 无注入：送达率 | 无注入：P50 / P99 ms | netem：送达率 | netem：吞吐 msg/s | netem：P50 / P99 ms |
| --- | --- | --- | --- | --- | --- | --- |
| 突发 | 0 | 100% | 576 / 1087 | 100% | 3870（-8%） | 681 / 1215 |
| 突发 | 1 | 100% | 1046 / 1985 | 100% | 1197（**-51%**） | 1721 / 3962 |
| 限速 50 条/s | 0 | 100% | 3.1 / 4.3 | 100% | 498 | 94.9 / **519** |
| 限速 50 条/s | 1 | 100% | 3.4 / 5.7 | 100% | 474 | 99.1 / **686** |

- 5% 的 IP 层丢包被 TCP 重传完全掩盖，QoS 0 和 QoS 1 送达率都是 100%；代价体现在延迟：P50 ≈ 往返 2 × 50 ms，P99 被重传超时（RTO ≥ 200 ms）拉到 0.5–0.7 s。
- QoS 1 每条消息多一次 PUBACK 往返，inflight 窗口（20 条）在高 RTT 下很快填满，突发吞吐降一半；QoS 0 只降 8%。
- 结合第一轮的“网络中断”实验：对 MQTT 而言，QoS 0 丢消息的主要原因是连接中断（送达率 54.98%），而不是随机丢包；
  QoS 1 加持久会话在两种场景下都做到零丢失。

### 网关多 worker（SO_REUSEPORT）

`devtools/loadtest/rest_workers.py`：压测端 8 个进程 × 16 并发，每个接口 10 秒，业务服务 1 个进程。

| 网关 worker | 接口 | 吞吐 req/s | P50 ms | P99 ms |
| --- | --- | --- | --- | --- |
| 1 | /health（只到网关） | 7521 | 16.9 | 21.0 |
| 4 | /health | **18728**（2.5×） | 6.5 | 12.2 |
| 1 | /api/templates（代理到业务服务） | 2034 | 62.8 | 71.7 |
| 4 | /api/templates | **2700** | 47.3 | 53.7 |

- **压测发现并修复的问题**：网关原来在 `asyncio.run()` 内部才 fork 出 worker，子进程继承了父进程正在运行的事件循环与同一个 epoll 实例，
  4 个 worker 的吞吐和 1 个完全一样。改为在创建事件循环之前 fork（`gleaner/__main__.py`）后，`/health` 提升到 2.5 倍。
- `/api/templates` 只提升 33%，此时瓶颈在单进程的业务服务；compose 里业务服务也可以多开实例（网关一致性哈希分流）。
- 两种部署都远超 proposal 目标（2 核、缓存命中 ≥ 1000 req/s）。

## 第三轮：Docker Compose（WSL 2 里的 Docker Engine 29.9，2026-10-22）

`docker compose -f deploy/docker-compose.yml --profile dev up -d --build` 启动 12 个容器（PostgreSQL、业务服务、2 个推送节点、
网关 2 worker、Broker、采集、邮件服务、Prometheus、Grafana、fake_moodle、GreenMail），然后 `python devtools/compose_demo.py`
经发布端口跑一遍演示路径（用 requests / websockets / paho-mqtt / imaplib 做对照客户端）。逐步结果在 `results/compose_demo.json`。

| 步骤 | 结果 |
| --- | --- |
| 注册验证码邮件（平台发信 → GreenMail，IMAP 取回） | 通过 |
| Moodle 模板登录、采集 7 个作业 | 通过 |
| WebSocket 经网关接入推送节点，hello 补发 | 通过 |
| 老师把截止提前 2 天 → WebSocket 收到“截止提前”，MQTT 收到 `gleaner/u/<uid>/urgent` | 通过 |
| `docker compose stop` 该用户所在的推送节点 → 重连到另一节点，补发宕机期间的变化 | 通过（两个方向都测过） |
| 学校邮箱来源（IMAP 连 GreenMail） | 通过 |
| Prometheus 6 个抓取目标全部 up、Grafana 正常 | 通过 |
| 浏览器打开 `http://localhost:8080`，登录后看板与实时连接（`/ws`、`/mqtt`） | 通过 |

同一套环境连续跑多次（多个用户、推送节点反复启停）都通过。

### compose 实测发现并修复的问题

之前测试全部跑在 SQLite、单用户、进程内组合上，下面这些问题只有在真实部署里才会出现：

| # | 现象 | 原因 | 修复 |
| --- | --- | --- | --- |
| 1 | 首次启动时某个推送节点崩溃重启 | 多个服务同时 `CREATE TABLE IF NOT EXISTS`，PostgreSQL 并发建表撞 `pg_type` 唯一约束 | 建表加会话级咨询锁（`storage/db.py`）；迁移在 PostgreSQL 上用 `ADD COLUMN IF NOT EXISTS` |
| 2 | 采集全部失败：`argument of CASE/WHEN must be type boolean` | `CASE WHEN ? THEN`：SQLite 接受 0/1，PostgreSQL 要求布尔 | 改为 `CASE WHEN ? = 1`（两处） |
| 3 | PostgreSQL 重启后业务服务一直报 `the connection is closed` | 数据库连接断开后从不重连 | 下一条语句自动重连；事务中途不重连，断线那条不自动重试（写操作可能已执行） |
| 4 | 第二个用户登录同一个 Moodle 后看不到任何作业 | 事项身份键全局唯一（`moodle:<host>:assign:<cmid>`），第二个人的作业被当成第一个人那条“未变化”；按链接合并时还可能把个人邮件并进别人的事项 | 个人来源的身份键与别名键加所有者前缀，只与本人或公共来源的事项合并；迁移补齐已有数据（`core/pipeline.py: _scope`） |
| 5 | 推送节点重启后，接入它的用户收不到任何推送 | Hub 为下线节点保留去重表 60 秒，新进程的帧序号从 1 开始，SUBSCRIBE 被当成重复帧丢掉 | 节点进程在 NODE_JOIN 中带自己的 `epoch`，变化时 Hub 清空该成员的去重表（`docs/protocols/bus.md` §4） |
| 6 | 浏览器端一直显示“离线 · 显示缓存内容” | 浏览器本地数据库（drift）不可用时，`refreshAll` 写缓存抛异常，实时连接根本没建立 | 本地缓存读写失败只影响离线浏览；实时连接与操作照常（队列写不进时直接发送） |
| 7 | 网关多 worker 不生效（第二轮压测发现） | 在事件循环内 fork | 见第二轮“网关多 worker” |
| 8 | 容器里 Moodle Web Service 从未生效（接入 MUST 时发现），一直回退网页解析 | `urljoin(base, "/webservice/rest/server.php?")`：容器里的 Python 3.12 会丢掉末尾空的“?”，拼成 `server.phpwstoken=…`；本机 Python 3.14 不会，所以测试没发现 | 统一用 `collector/session.py: moodle_ws_url` 拼地址；回归测试 `test_moodle_ws_url_keeps_query_separator` |

每个问题都补了回归测试。另外新增 `GLEANER_TEST_PG`：设置后，用到数据库的测试改跑 PostgreSQL；`test_core`、`test_e2e`、`test_mail`、`test_storage_pg` 共 40 项在 PostgreSQL 上全部通过。

compose 文件本身的调整：新增 `.dockerignore`（构建上下文从 ~250 MB 降到只含 `server/`、`client/build/web`、`devtools/fake_moodle`）；
Autobahn 镜像标签 `0.8.2` 在 Docker Hub 不存在，改为 `25.10.1`；Linux Docker Engine 没有 `host.docker.internal`，autobahn 服务加 `extra_hosts`。

### WebSocket 一致性：官方 Autobahn Testsuite

`crossbario/autobahn-testsuite:25.10.1` 的 fuzzingclient 模式，对两套自研实现各跑 301 个用例（排除 12.*、13.* 压缩扩展），
回显服务器 `devtools/autobahn_echo.py`，汇总脚本 `devtools/autobahn_summary.py`，结果 `results/autobahn.json`
（完整 HTML 报告在 `deploy/autobahn/reports/servers/`，约 11 MB，不入库）。全程约 2 小时 17 分钟。

| 实现 | OK | NON-STRICT | INFORMATIONAL | FAILED |
| --- | --- | --- | --- | --- |
| asyncio 版（`websocket_route`，网关、本地代理等） | 289 | 9 | 3 | **0** |
| 手写反应器版（推送节点；浏览器 `/ws` 经网关原样转发到这里） | 251 | 12 | 3 | 35（全部是二进制回显，见下） |

- Autobahn 把 NON-STRICT、INFORMATIONAL 视为合规：NON-STRICT 是遇到协议错误时比严格要求更早关闭连接（例如收到保留 opcode 时不先回显之前的消息），
  INFORMATIONAL 是关闭码等信息性记录。
- 反应器版的 35 个 FAILED 全部是二进制消息用例（1.2.*、9.2.*、9.4.*、9.6.*、9.8.*）：推送节点只收发文本帧，回显服务器只回显文本。
  文本类用例（含 9.1、9.3、9.5、9.7 的 16 MB 大消息与分片性能用例）全部通过。
- 第一次运行时 asyncio 版有 4 个 FAILED（9.1.5、9.1.6、9.2.5、9.2.6，8 MB / 16 MB 消息）：实现的单条消息上限是 4 MB，
  超出按 §7.4.1 以 1009 关闭，属于设计限制而不是协议错误。现在上限可配置（`websocket_route(max_message=…)`、`ReactorWSServer(max_message=…)`），
  生产默认仍为 4 MB，回显服务器放宽到 32 MB 后全部通过。
- 精简版 `autobahn_lite.py`（38 个用例，不需要 Docker）仍保留，用于日常快速回归。

### 仍待完成

| 项目 | 原因 |
| --- | --- |
| 实验 5：跨机器扩容 | 需要 2–3 台机器（云服务器） |
| Wireshark 抓包 | 需要图形界面手工操作：抓 `lo`，过滤 `tcp.port == 18100` 等 |
| 浏览器本地缓存 | Claude 应用内置浏览器里 drift 的 Worker 取 `sqlite3.wasm` 报 `Failed to fetch`（文件本身可正常下载），待在 Chrome / Edge 中确认是否只是该浏览器的限制 |
