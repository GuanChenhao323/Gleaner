# 100 个目标同时到期时，如何隔离慢站点

设计草案 · 2026-11-18 · 范围为单进程后端 HTTP 监测。下文的时限、并发数和图表均用于设计实验，尚无实测结果。

**核心决定：按站点排队，跨站并发，同站限速。** 一个站点读响应时，最多占用一个执行名额；它进入冷却后，释放这个名额。能否按时完成，要用健康站点从原定到期到检查结果落盘的时间来验收。

## 现有 Scheduler 的三个约束

| 现状 | 对设计的影响 |
| --- | --- |
| `Scheduler.tick()` 在整轮持锁，逐个等待 `_execute()`，每次执行后还等待 `handoff.drain()`。 | 即使两个来源属于不同站点，后者也要等前者读取和交付完毕。 |
| 一个 Scheduler 绑定一套 Registry、站点策略、transport 和 Moodle adapter。`_runtime()` 读取无站点维度的 `host_not_before`；transport 的锁和信号量属于各自实例。 | 多站点需显式路由并共享全局并发预算。按页面各建一个 transport 会拆散同站限速，复用一个冷却键则会让其他站点一起暂停。 |
| Registry 已按所有者、适配器、规范化 URL、认证上下文合并同页条目。相同账号或浏览器桥接下，同轮到期来源先形成快照，再推进下一轮时间。 | 调度单位沿用来源，一次请求可观察多个目标。必须保留同轮资格，否则首个来源推进账号时钟后，其余来源可能被推迟一个周期。 |

对应实现见 [Scheduler](../../../server/gleaner/monitoring/scheduler.py)、[Registry](../../../server/gleaner/monitoring/registry.py)、[HTTP transport](../../../server/gleaner/monitoring/transport.py) 和 [Handoff](../../../server/gleaner/monitoring/handoff.py)。现有 [PageMonitor](../../../server/gleaner/monitoring/pages.py) 有独立的页面检查入口。本方案需给 Scheduler 增加受信站点路由和测试页面适配器；浏览器标签页的执行与接管另见[现有计划](2026-11-17-browser-backend-monitor-handoff.md)。

## I/O 多路复用怎样支撑跨站并发

现有 HTTP transport 已经使用 `httpx.AsyncClient` 和异步响应流。当 socket 暂时不可读时，当前协程让出执行权，事件循环可以服务其他就绪连接。但原 Scheduler 在循环内等待整个 `_execute()` 完成，此时它还没派发本轮下一个来源。因此，原策略已支持异步网络 I/O，**同轮监测请求仍然串行**。在当前 Mac 的系统 Python 上，新建 asyncio 事件循环实际得到 `KqueueSelector`；正式实验记录所用 Python、操作系统、事件循环及其后端。

新方案在同一事件循环内保留最多 8 个在途检查。以场景 B 为例，Moodle 的第一个请求发出后等 8 秒，读取协程挂起，第 2 至第 60 个 Moodle 作业继续留在站点队列。其余 7 个名额可以先服务 7 个公开站，随后哪个连接先就绪，就继续读哪个响应；健康页完成后，名额继续交给其他就绪站点。等待 socket 的工作由事件循环复用，**哪些检查能占名额由 Scheduler 决定**。同站访问间隔、认证锁和冷却条件都在占用全局名额前检查。

transport 的 `Semaphore(4)` 属于单个实例，且同实例的请求还持有一把覆盖响应读取的锁。实验按站点共享访问约束，跨站使用各自的 transport，由上层统一控制 8 个名额。HTML 解析和同步 SQLite 事务仍占用事件循环线程；如果健康请求已就绪却迟迟不能推进，应测量这两段耗时，再决定是否需要调整执行方式。

## 一轮到期任务怎样运行

1. **分组。** 调度器在到期时刻取快照，把有资格的来源按受信策略的 origin（协议、主机、有效端口）放进站点队列。若多个 origin 在配置中共用上游配额，则进入同一限速组。不同账号访问同一站点时共享站点额度，各自使用原认证上下文。每个来源沿用一个有效检查 ID 和原到期时间；运行期间重复触发只合并一次，已有结果待交付的来源不再抓取。
2. **排队。** 各站内部按原到期时间排序，同一时间以稳定的来源 ID 打破平局。调度器在可运行站点间轮转，一次从一个站点取一个来源，再将该站移到队尾。处于冷却、未到启动间隔或会话正忙的来源留在队列；同站还有其他符合条件的来源时可以先行。首版用每站最多 1 个、全局最多 8 个在途检查作为实验参数。
3. **派发。** 用短锁一次性认领检查、站点和可用会话，预留全局名额后才启动网络操作。每次请求完成、会话释放、新一批来源到期或冷却截止，都唤醒同一个派发循环。网络等待发生在锁外。这样下一批来源即使在上一批慢请求结束前到期，也能参与轮转。保持单来源单次执行，重复调用 tick 不会启动第二个派发器。
4. **释放与退避。** 成功时先复核来源版本和认证代次，再将结果及检查状态原子写入 outbox，随即释放名额。超时、取消和异常也必须释放。某站返回 `429 / Retry-After: 60` 时先持久化该站冷却截止时间，再释放名额；60 秒内其余站点继续工作。单页读超时沿用来源级退避。冷却结束后，站点重新参与轮转，按原访问间隔恢复。

**执行边界。** 每个来源通过受信配置选择适配器、认证上下文和 transport；同一限速组的页面、账号、robots 请求和重定向共享实际请求间隔。保留 transport 的超时和最终限速校验。旧的 `host_not_before` 在升级时只归入原绑定站点；账号轮次键也按站点和原账号或桥接身份区分。已入队的同轮检查保留资格，派发时仍复核启用状态、版本和认证。计划到期时间随检查持久化，进程重启时用它恢复队列与延迟口径。

**交付与积压。** 单独的交付循环按已有回执规则消费 outbox。派发前为每个在途检查预留一个结果位置，待交付批次与预留位置之和达到现有 `max_pending` 时停止新派发。待执行意图继续保存在存储中，交付腾出空间后恢复。共享存储或交付端持续饱和会触发全局背压，因此健康站点的时限以这些下游资源有余量为前提。

## 两个高并发场景

**要检验的假设**是：在同一批 100 页同时到期、其中一个站点持续慢响应时，按站轮转能在两种负载下都降低健康页面的 P95 检查延迟。实验同时量化整批吞吐量、P99、CPU、内存和控制开销。单站有自己的限速，健康页面提早完成与最后一页提早完成是两个独立结果。

| 实验条件 | A · 公开来源分散 | B · Moodle 来源集中 |
| --- | --- | --- |
| 同时到期的 100 页 | 附录一的 50 个不同站点。知乎 1 页、Python 3 页，其余 48 站各 2 页 | 同一测试会话的 60 个 Moodle 作业页，加附录一 **01–40 号站点各自的第一个页面**。共 41 个站点 |
| 慢站注入 | Go 站点的 2 页均延迟 8 秒，其余 **98 页**健康 | Moodle 的 60 页均延迟 8 秒，其余 **40 页**健康 |
| 核心问题 | 少量慢页面散在队列中，其他 49 站要等多久？ | 60% 的到期任务集中在一个慢站，其他 40 站还能否及时完成？ |
| 主比较 | 原 Scheduler 与按站轮转的健康页 P95，另报第 30 秒完成数 / 98 | 同样比较健康页 P95，另报第 50 秒完成数 / 40 |

“同时到期”指同一个单调时钟起点有 100 项可调度工作。原策略一次执行 1 项，新策略最多同时执行 8 项，每站最多 1 项。每个来源只挂一个目标，每轮只触发一次。两案的健康页面均在收到请求后等待 100 毫秒再发响应头，慢页等待 8 秒并最终成功返回相同内容。延迟由回放服务异步注入，Go 与 Moodle 仅是选定的故障组。每案另跑一次全站 100 毫秒的对照条件，健康子集仍按同一批 98 / 40 个 URL 统计。429 冷却可以另做功能验证，主实验始终使用慢响应。

### 网页从哪里来，压力打到哪里

附录给出真实 URL 和样本选法。**页面身份来自真实站点，定时并发流量发往本地 HTTP 回放服务**。回放使用独立进程与真实 TCP socket，一个原始 origin 映射一个本地监听端口，保留同站分组、页面路径及查询参数。这样两种策略遇到的波形、正文长度与解析工作量可以完全一致，结果适用于受控 HTTP 工作负载，公网 DNS、TLS、实时带宽和 CDN 波动不在本轮测量范围内。

准备实验时，为每个 URL 冻结相同响应并登记来源、内容类型、正文大小、摘要和一个可核对的标记（列表首项、页面主标题或作业 ID）。公开页采样遇到登录墙、错误壳或无法稳定离线复现的动态内容时，记录状态，使用明确标记的结构化模拟页，分别报告原文快照和模拟页数量。Moodle 依据附录二的真实作业链接，在本地沿用[合成作业页面](../../../devtools/fake_moodle/monitoring_fixture.py)的登录与解析结构，为不同 ID 生成匹配的作业标记；只用测试会话和合成正文。正式计时前验证 100 个不同 URL、预期站点数、正确内容与回放哈希。两组策略读取同一份冻结清单。

## Baseline 与公平对照

**Baseline 固定为仓库版本 `e0a9f24` 的监控模块 [Scheduler.tick()](../../../server/gleaner/monitoring/scheduler.py)。** 它从 [Store.sources()](../../../server/gleaner/monitoring/store.py) 按 `source_id` 排序读来源，先形成同轮到期快照，然后依次等待每个来源的 `_execute()` 和 `handoff.drain()`。慢页位于队首、中间、队尾，造成的等待不同，所以输入顺序也必须配对。

1. **共用运行环境。** 多站实验需要两边共用同一套实验路由、公开页适配器、Moodle 适配器、HTTP transport、单站访问策略、SQLite 磁盘库和本地快速 sink。baseline 保留原来的逐项等待顺序，新方案使用上文的站点轮转与异步交付。结论比较两套完整策略；另记录排队和交付阶段耗时，避免将交付上的差异全归给站点轮转。
2. **每轮独立启动。** 使用相同机器和 CPU 配额，固定同站启动间隔 2 秒、总请求超时 30 秒、检查周期 600 秒及 outbox 上限 100。预热 robots、建立测试会话、清空待交付结果再统一到期，桥接心跳持续在线。使用磁盘数据库和相同的内容校验规则。两边都记录重试、失败及被限速的请求。
3. **成对重复。** 每个场景、每个延迟条件预先固定 20 组排列种子。每个种子把同一组已排序来源 ID 分配给随机排列后的页面，复制同一初始状态给两套策略；交替 baseline 先跑和新方案先跑。每轮到全部终态且交付清空，或第 590 秒硬截止；只观察第 0 秒这批任务。20 组种子 × 2 种策略 × 2 个延迟条件 × 2 个场景，共 160 轮。不得只选择慢站恰好排在第一的轮次。
4. **保留两端轨迹。** 调度端记录轮次、来源、原定到期、派发、请求开始、结果事务提交、交付回执和最终状态；回放服务独立记录站点、请求用途、到达和响应时刻、响应字节与在途数。用检查 ID 关联。进程内时间差使用单调时钟。原代码的检查创建时间可能晚于原定到期，直接拿它计算会漏掉串行排队。所有健康页都要核对内容，HTTP 200 的错误页不能计入成功。

### 怎样区分并发、站点配额和轮转的贡献

主实验的 160 轮保留原 Scheduler 作为 baseline。另做机制对照：在**同一个异步执行器**上固定 transport、每站 1 个在途检查、站点间隔、会话约束和交付方式，复用相同种子、页面和故障轨迹，比较下列三种配置。

| 配置 | 全局名额 | 名额空出时的选择 | 可回答的问题 |
| --- | ---: | --- | --- |
| 单名额，按到期顺序 | 1 | 选择全局队列中最早的可运行来源；同到期按来源 ID | 提供同一执行器上的串行参照，排除交付实现差异 |
| 多名额，按到期顺序 | 8 | 沿用上面完全相同的规则 | 对比上一行，看允许多个站点的网络等待重叠，单独带来多少收益 |
| 多名额，按站轮转 | 8 | 轮转可运行的站点，在站内选最早来源 | 对比上一行，看同样并发预算和站点配额下，轮转是否进一步改善健康页 P95 |

三组都跳过暂时不可运行的来源。若后两行结果相近，只能把主要收益归给有界跨站并发和两者共有的约束。上述三组没有单独改变每站配额，不能据此量化该配额的独立收益。8 是主实验参数；在固定轮转策略下可再测 1、2、4、8、16 个全局名额，结合尾延迟、CPU 和峰值 RSS 观察继续加并发何时失去收益。

**验证确有 I/O 重叠。** 回放端记录每次请求从到达到响应结束的区间，按站点绘制时间线，并统计全局及单站在途峰值。场景 B 应能看到多个公开页在某次 Moodle 的 8 秒等待窗口内开始并完成；baseline 的后续请求要等前一请求结束。另在调度进程用固定周期定时器记录实际唤醒相对计划时刻的延误，报告 P95，并结合解析与落盘耗时判断事件循环是否被同步工作阻塞。

## 指标为什么合理，具体怎样测

| 指标 | 采样与计算 | 它回答的问题 |
| --- | --- | --- |
| **主指标：健康页端到端 P95；同时报 P99** | 起点是计划到期，终点是正确结果写入 [Store.enqueue()](../../../server/gleaner/monitoring/store.py) 的事务提交。两时刻之差包含排队、等待会话、网络 I/O、解析和本地落盘。按健康子集和全部 100 页分别计算；另外记到 sink 回执的延迟，以检查交付是否积压。 | 慢站究竟让其余站点最晚完成的一批页面多等了多久？单量 HTTP 往返时间会漏掉派发前的等待。 |
| **有效吞吐量与整批耗时** | 每批成功落盘的不同来源数除以从同时到期到全部终态的秒数，单位“页/秒”；截止时仍未结束则用 590 秒并标“截尾”。另报固定 30 秒（A）、50 秒（B）内的健康成功数和窗口页/秒。每个来源最多计一次，重试单列。 | 页/秒直接对应监测工作量。整批耗时揭示慢站是否决定最后完成时间，固定窗口能显出健康页面提前交付的收益。 |
| **应用层有效数据率（Mbps）** | 两端按正文计数。将成功检查对应的响应正文字节总数乘 8 换成比特，除以同一整批耗时，再除以一百万得到 Mbps。冻结每个页面的大小、压缩方式，另列重试正文流量。 | 辅助说明传输了多少数据。页面大小会影响 Mbps，因此同时报告页/秒并注明正文口径；链路总流量需另行抓包。 |
| **CPU 时间与占用率** | 单独监测 Scheduler 进程。读取从同时到期至回执清空或硬截止的用户态和内核态 CPU 秒数增量，二者相加得每轮 CPU 总秒；除以同一观测时长再乘 100% 得平均占用率，100% 代表占满一个逻辑核。另列每成功页 CPU 毫秒。 | 平均占用率可能因任务更快完成而升高，总 CPU 时间可区分计算成本与更紧凑的执行。 |
| **内存** | 由独立采样进程每 100 毫秒读取 Scheduler 的 RSS，报告启动预热后的基线、运行峰值及峰值增量，单位 MiB；占比以固定给定的机器或容器内存为分母。两种策略都排除回放服务器、采样器和外部 sink 进程。 | 同时保留多份响应和解析结果可能抬高峰值。采样峰值注明采样间隔，便于复测。 |
| **控制信令开销** | 为每次请求记录用途。分别报告算法主动发送的探测/协调请求总数、每 100 个来源的探测数，以及对应字节。正常内容、robots、桥接心跳、重试分别计数。若需报告“包”，仅对回环测试端口抓包，按探测连接或请求关联统计实际 IP 包数，说明方向和是否含握手/ACK。 | 两种策略都可凭现有请求的耗时和响应做决策。若没有额外探测，应由日志给出 0；一次 HTTP 请求可能对应多个网络包。 |

**尾延迟的分母固定为本轮全部预定目标。** 按成功落盘时间排序，P95 取覆盖预定来源 95% 的第一个时刻，P99 同理，所需页数向上取整。以 B 的 40 个健康页为例，P95 读第 38 页，单轮 P99 读第 40 页。若成功数不足相应位置，就报“截止前未达到”，并列出失败、超时和仍待执行数。每个条件另汇总 20 轮页面样本，B 的健康子集有 800 个观测机会；汇总分位数须从页面记录重新计算，不能平均 20 个 P99。若报告区间，按整轮成对重采样，避免把同轮页面当作独立重复实验。

**如何判读。** 每个场景分别列出两种策略在慢站条件下的健康 P95、每个种子的配对差值，以及该差值的中位数与 95% 配对 bootstrap 区间。再比较两种策略从“全站健康”到“单站变慢”各增加了多少健康页 P95，用来区分一般并发提速与故障隔离。只有两个场景均有一致的配对改善、区间支持改善、成功数未减少且同站访问约束均满足，才报告“两场景健康尾延迟均改善”。吞吐量与资源分别给实测值，支持到哪项就报告到哪项。

## PPT 呈现

主图放两组配对柱，横轴分别是“A · 50 个公开站点”和“B · Moodle 占 60 页”，纵轴从零开始，单位为秒。每组两根柱是原 Scheduler 和按站轮转，柱高取 20 轮健康页 P95 的中位数；旁边标注配对差值及区间。图注列出健康样本数 A=98、B=40，以及同站启动间隔和并发预算。下一行小表报告全批页/秒、P99、CPU 秒、峰值 RSS、探测请求数。实测后填值。

## 附录一 · 100 个公开网页，50 个站点

每行对应一个不同主机和一个独立的实验站点队列。每个链接是一项独立检查；Reddit 的两个社区共享同一个站点额度。链接均通过公开网页索引核对过页面内容或标题，运行环境的匿名 HTTP 可读性在建回放集时逐页检验。知乎发现页可核对，热榜本次返回 403，已排除。B 只取 01–40 的第一列链接，每站恰好一页。

| 编号 | 站点 | 真实页面（按选样顺序） |
| --- | --- | --- |
| 01 | 知乎 · `www.zhihu.com` | [/explore](https://www.zhihu.com/explore) |
| 02 | Reddit · `www.reddit.com` | [/r/programming/](https://www.reddit.com/r/programming/) · [/r/Python/](https://www.reddit.com/r/Python/) |
| 03 | Hacker News · `news.ycombinator.com` | [/newest](https://news.ycombinator.com/newest) · [/show](https://news.ycombinator.com/show) |
| 04 | V2EX · `www.v2ex.com` | [/go/python](https://www.v2ex.com/go/python) · [/go/programmer](https://www.v2ex.com/go/programmer) |
| 05 | Stack Overflow · `stackoverflow.com` | [/questions/tagged/python](https://stackoverflow.com/questions/tagged/python) · [/questions/tagged/network-programming](https://stackoverflow.com/questions/tagged/network-programming) |
| 06 | Python · `www.python.org` | [/downloads/](https://www.python.org/downloads/) · [/events/](https://www.python.org/events/) · [/about/](https://www.python.org/about/) |
| 07 | Go · `go.dev` | [/blog/](https://go.dev/blog/) · [/doc/](https://go.dev/doc/) |
| 08 | Rust · `rust-lang.org` | [/learn/](https://rust-lang.org/learn/) · [/tools/](https://rust-lang.org/tools/) |
| 09 | Ruby · `www.ruby-lang.org` | [/en/news/](https://www.ruby-lang.org/en/news/) · [/en/downloads/](https://www.ruby-lang.org/en/downloads/) |
| 10 | Julia · `julialang.org` | [/downloads/](https://julialang.org/downloads/) · [/blog/](https://julialang.org/blog/) |
| 11 | Kotlin · `kotlinlang.org` | [/docs/home.html](https://kotlinlang.org/docs/home.html) · [/docs/releases.html](https://kotlinlang.org/docs/releases.html) |
| 12 | Swift · `www.swift.org` | [/blog/](https://www.swift.org/blog/) · [/install/](https://www.swift.org/install/) |
| 13 | Dart · `dart.dev` | [/overview](https://dart.dev/overview) · [/language](https://dart.dev/language) |
| 14 | TypeScript · `www.typescriptlang.org` | [/docs/](https://www.typescriptlang.org/docs/) · [/play/](https://www.typescriptlang.org/play/) |
| 15 | Lua · `www.lua.org` | [/news.html](https://www.lua.org/news.html) · [/versions.html](https://www.lua.org/versions.html) |
| 16 | Node.js · `nodejs.org` | [/en/blog](https://nodejs.org/en/blog) · [/en/about](https://nodejs.org/en/about) |
| 17 | Django · `www.djangoproject.com` | [/weblog/](https://www.djangoproject.com/weblog/) · [/download/](https://www.djangoproject.com/download/) |
| 18 | FastAPI · `fastapi.tiangolo.com` | [/tutorial/](https://fastapi.tiangolo.com/tutorial/) · [/release-notes/](https://fastapi.tiangolo.com/release-notes/) |
| 19 | Flask · `flask.palletsprojects.com` | [/en/stable/quickstart/](https://flask.palletsprojects.com/en/stable/quickstart/) · [/en/stable/changes/](https://flask.palletsprojects.com/en/stable/changes/) |
| 20 | PostgreSQL · `www.postgresql.org` | [/download/](https://www.postgresql.org/download/) · [/docs/](https://www.postgresql.org/docs/) |
| 21 | SQLite · `sqlite.org` | [/news.html](https://sqlite.org/news.html) · [/changes.html](https://sqlite.org/changes.html) |
| 22 | Redis · `redis.io` | [/docs/latest/](https://redis.io/docs/latest/) · [/blog/](https://redis.io/blog/) |
| 23 | MariaDB · `mariadb.org` | [/download/](https://mariadb.org/download/) · [/about/](https://mariadb.org/about/) |
| 24 | Nginx · `nginx.org` | [/en/download.html](https://nginx.org/en/download.html) · [/en/docs/](https://nginx.org/en/docs/) |
| 25 | HAProxy · `www.haproxy.org` | [/](https://www.haproxy.org/) · [/download/](https://www.haproxy.org/download/) |
| 26 | curl · `curl.se` | [/changes.html](https://curl.se/changes.html) · [/docs/](https://curl.se/docs/) |
| 27 | Git · `git-scm.com` | [/docs/git-log](https://git-scm.com/docs/git-log) · [/book/en/v2](https://git-scm.com/book/en/v2) |
| 28 | GitHub · `github.com` | [/python/cpython/releases](https://github.com/python/cpython/releases) · [/golang/go](https://github.com/golang/go) |
| 29 | GitLab · `about.gitlab.com` | [/blog/](https://about.gitlab.com/blog/) · [/platform/](https://about.gitlab.com/platform/) |
| 30 | Debian · `www.debian.org` | [/News/](https://www.debian.org/News/) · [/releases/](https://www.debian.org/releases/) |
| 31 | Ubuntu · `ubuntu.com` | [/blog](https://ubuntu.com/blog) · [/download](https://ubuntu.com/download) |
| 32 | Arch Linux · `archlinux.org` | [/news/](https://archlinux.org/news/) · [/packages/](https://archlinux.org/packages/) |
| 33 | FreeBSD · `www.freebsd.org` | [/releases/](https://www.freebsd.org/releases/) · [/where/](https://www.freebsd.org/where/) |
| 34 | OpenBSD · `www.openbsd.org` | [/](https://www.openbsd.org/) · [/faq/](https://www.openbsd.org/faq/) |
| 35 | NetBSD · `www.netbsd.org` | [/releases/](https://www.netbsd.org/releases/) · [/docs/](https://www.netbsd.org/docs/) |
| 36 | Alpine Linux · `alpinelinux.org` | [/posts/](https://alpinelinux.org/posts/) · [/downloads/](https://alpinelinux.org/downloads/) |
| 37 | NumPy · `numpy.org` | [/news/](https://numpy.org/news/) · [/learn/](https://numpy.org/learn/) |
| 38 | Linux kernel · `www.kernel.org` | [/](https://www.kernel.org/) · [/releases.html](https://www.kernel.org/releases.html) |
| 39 | Kubernetes · `kubernetes.io` | [/blog/](https://kubernetes.io/blog/) · [/docs/home/](https://kubernetes.io/docs/home/) |
| 40 | Docker · `www.docker.com` | [/blog/](https://www.docker.com/blog/) · [/products/docker-desktop/](https://www.docker.com/products/docker-desktop/) |
| 41 | IETF · `www.ietf.org` | [/blog/](https://www.ietf.org/blog/) · [/meeting/](https://www.ietf.org/meeting/) |
| 42 | W3C · `www.w3.org` | [/news/](https://www.w3.org/news/) · [/standards/](https://www.w3.org/standards/) |
| 43 | IANA · `www.iana.org` | [/domains](https://www.iana.org/domains) · [/protocols](https://www.iana.org/protocols) |
| 44 | RFC Editor · `www.rfc-editor.org` | [/rfc/rfc9110.html](https://www.rfc-editor.org/rfc/rfc9110.html) · [/rfc/rfc9293.html](https://www.rfc-editor.org/rfc/rfc9293.html) |
| 45 | MDN · `developer.mozilla.org` | [/en-US/docs/Web/HTTP](https://developer.mozilla.org/en-US/docs/Web/HTTP) · [/en-US/docs/Web/API/WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket) |
| 46 | MIT News · `news.mit.edu` | [/topic/computers](https://news.mit.edu/topic/computers) · [/topic/engineering](https://news.mit.edu/topic/engineering) |
| 47 | pandas · `pandas.pydata.org` | [/about/](https://pandas.pydata.org/about/) · [/docs/](https://pandas.pydata.org/docs/) |
| 48 | NASA · `www.nasa.gov` | [/missions/](https://www.nasa.gov/missions/) · [/news/recently-published/](https://www.nasa.gov/news/recently-published/) |
| 49 | CERN · `home.cern` | [/news](https://home.cern/news) · [/science](https://home.cern/science) |
| 50 | arXiv · `arxiv.org` | [/list/cs.NI/recent](https://arxiv.org/list/cs.NI/recent) · [/list/cs.DC/recent](https://arxiv.org/list/cs.DC/recent) |

## 附录二 · 60 个真实 Moodle 作业入口

通过已登录的 [MUST Moodle Dashboard](https://moodle.must.edu.mo/my/) 进入课程页，读取页面列出的作业链接。共识别 61 个不同活动 ID，按下表固定 60 个，数值计算的第三个作业留作备选。核对层级是课程页上的真实链接；此次未逐页读取提交记录、作业正文或成绩。附录只记录课程名和活动入口，复现压测无需访问校内账号。

| 课程来源 | 数量 | 作业页面（链接文字为活动 ID） |
| --- | ---: | --- |
| [网络编程](https://moodle.must.edu.mo/course/view.php?id=120278) | 8 | [990318](https://moodle.must.edu.mo/mod/assign/view.php?id=990318)、[996452](https://moodle.must.edu.mo/mod/assign/view.php?id=996452)、[1000602](https://moodle.must.edu.mo/mod/assign/view.php?id=1000602)、[1005231](https://moodle.must.edu.mo/mod/assign/view.php?id=1005231)、[1012786](https://moodle.must.edu.mo/mod/assign/view.php?id=1012786)、[1014480](https://moodle.must.edu.mo/mod/assign/view.php?id=1014480)、[1016184](https://moodle.must.edu.mo/mod/assign/view.php?id=1016184)、[1017386](https://moodle.must.edu.mo/mod/assign/view.php?id=1017386) |
| [数据科学](https://moodle.must.edu.mo/course/view.php?id=120348) | 3 | [973192](https://moodle.must.edu.mo/mod/assign/view.php?id=973192)、[1008741](https://moodle.must.edu.mo/mod/assign/view.php?id=1008741)、[1016482](https://moodle.must.edu.mo/mod/assign/view.php?id=1016482) |
| [移动应用开发](https://moodle.must.edu.mo/course/view.php?id=120238) | 12 | [970022](https://moodle.must.edu.mo/mod/assign/view.php?id=970022)、[980086](https://moodle.must.edu.mo/mod/assign/view.php?id=980086)、[987574](https://moodle.must.edu.mo/mod/assign/view.php?id=987574)、[992251](https://moodle.must.edu.mo/mod/assign/view.php?id=992251)、[994394](https://moodle.must.edu.mo/mod/assign/view.php?id=994394)、[997399](https://moodle.must.edu.mo/mod/assign/view.php?id=997399)、[1001229](https://moodle.must.edu.mo/mod/assign/view.php?id=1001229)、[1004536](https://moodle.must.edu.mo/mod/assign/view.php?id=1004536)、[1004538](https://moodle.must.edu.mo/mod/assign/view.php?id=1004538)、[1008020](https://moodle.must.edu.mo/mod/assign/view.php?id=1008020)、[1015184](https://moodle.must.edu.mo/mod/assign/view.php?id=1015184)、[1015228](https://moodle.must.edu.mo/mod/assign/view.php?id=1015228) |
| [深度学习](https://moodle.must.edu.mo/course/view.php?id=112043) | 6 | [909934](https://moodle.must.edu.mo/mod/assign/view.php?id=909934)、[916664](https://moodle.must.edu.mo/mod/assign/view.php?id=916664)、[927542](https://moodle.must.edu.mo/mod/assign/view.php?id=927542)、[934440](https://moodle.must.edu.mo/mod/assign/view.php?id=934440)、[937100](https://moodle.must.edu.mo/mod/assign/view.php?id=937100)、[944442](https://moodle.must.edu.mo/mod/assign/view.php?id=944442) |
| [计算机网络实验 II](https://moodle.must.edu.mo/course/view.php?id=112025) | 5 | [902356](https://moodle.must.edu.mo/mod/assign/view.php?id=902356)、[919424](https://moodle.must.edu.mo/mod/assign/view.php?id=919424)、[930068](https://moodle.must.edu.mo/mod/assign/view.php?id=930068)、[936156](https://moodle.must.edu.mo/mod/assign/view.php?id=936156)、[944141](https://moodle.must.edu.mo/mod/assign/view.php?id=944141) |
| [计算机网络 II](https://moodle.must.edu.mo/course/view.php?id=112021) | 1 | [943544](https://moodle.must.edu.mo/mod/assign/view.php?id=943544) |
| [软件项目管理](https://moodle.must.edu.mo/course/view.php?id=112009) | 1 | [944190](https://moodle.must.edu.mo/mod/assign/view.php?id=944190) |
| [计算机程序设计](https://moodle.must.edu.mo/course/view.php?id=72488) | 7 | [529220](https://moodle.must.edu.mo/mod/assign/view.php?id=529220)、[565416](https://moodle.must.edu.mo/mod/assign/view.php?id=565416)、[565417](https://moodle.must.edu.mo/mod/assign/view.php?id=565417)、[565418](https://moodle.must.edu.mo/mod/assign/view.php?id=565418)、[583676](https://moodle.must.edu.mo/mod/assign/view.php?id=583676)、[569891](https://moodle.must.edu.mo/mod/assign/view.php?id=569891)、[591240](https://moodle.must.edu.mo/mod/assign/view.php?id=591240) |
| [操作系统](https://moodle.must.edu.mo/course/view.php?id=104900) | 5 | [843016](https://moodle.must.edu.mo/mod/assign/view.php?id=843016)、[843384](https://moodle.must.edu.mo/mod/assign/view.php?id=843384)、[848665](https://moodle.must.edu.mo/mod/assign/view.php?id=848665)、[864374](https://moodle.must.edu.mo/mod/assign/view.php?id=864374)、[871632](https://moodle.must.edu.mo/mod/assign/view.php?id=871632) |
| [计算机网络 I](https://moodle.must.edu.mo/course/view.php?id=104912) | 1 | [880612](https://moodle.must.edu.mo/mod/assign/view.php?id=880612) |
| [软件工程](https://moodle.must.edu.mo/course/view.php?id=104892) | 9 | [837584](https://moodle.must.edu.mo/mod/assign/view.php?id=837584)、[861374](https://moodle.must.edu.mo/mod/assign/view.php?id=861374)、[853864](https://moodle.must.edu.mo/mod/assign/view.php?id=853864)、[841020](https://moodle.must.edu.mo/mod/assign/view.php?id=841020)、[850262](https://moodle.must.edu.mo/mod/assign/view.php?id=850262)、[858634](https://moodle.must.edu.mo/mod/assign/view.php?id=858634)、[858658](https://moodle.must.edu.mo/mod/assign/view.php?id=858658)、[873804](https://moodle.must.edu.mo/mod/assign/view.php?id=873804)、[873808](https://moodle.must.edu.mo/mod/assign/view.php?id=873808) |
| [数值计算](https://moodle.must.edu.mo/course/view.php?id=107008) | 2 | [851478](https://moodle.must.edu.mo/mod/assign/view.php?id=851478)、[855328](https://moodle.must.edu.mo/mod/assign/view.php?id=855328) |
