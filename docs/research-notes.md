# 调研笔记：参考了哪些开源项目，借鉴了什么

| 来源 | 借鉴点 | 落在本项目哪里 |
| --- | --- | --- |
| [python-hyper/h11](https://github.com/python-hyper/h11) | sans-IO：协议状态机只处理字节，I/O 由外层负责；`RemoteProtocolError` 携带建议状态码（431 等）；协议切换后把剩余字节交给新协议 | `net/http/parser.py` 的 `ParseError.status`、`take_buffer()`；服务端与客户端共用一个解析器 |
| [python-hyper/wsproto](https://github.com/python-hyper/wsproto) | WebSocket 也做成 sans-IO；分片消息显式重组；ping 自动生成 pong；UTF-8 跨分片增量校验 | `net/websocket/protocol.py` 的 `WSConnection.receive_data()` 返回 (事件, 待回写字节) |
| [eclipse/mosquitto](https://github.com/eclipse/mosquitto)、[Yakifo/amqtt](https://github.com/Yakifo/amqtt) | 订阅树按层组织；`sport/#` 匹配父层；`$` 主题不被通配符匹配；同 ClientId 会话接管；空负载保留消息即删除；新订阅收到保留消息时 RETAIN=1，正常转发 RETAIN=0 | `net/mqtt/topics.py` 的 `SubscriptionTree`，`broker/broker.py` |
| [dgtlmoon/changedetection.io](https://github.com/dgtlmoon/changedetection.io) | 区分“没有变化”与“检查失败”，失败时不写快照；记录 last_checked / last_error / 连续失败次数；只在需要时比较快照 | `collector/engine.py` 的 `not_modified` / `failed` / `need_login` 三态，`sources.fail_count`；我们额外用了条件请求 |
| [C0D3D3V/Moodle-DL](https://github.com/C0D3D3V/Moodle-DL)、[moodlehq/moodleapp](https://github.com/moodlehq/moodleapp) | 用 `login/token.php?service=moodle_mobile_app` 换取 Web Service token，调用 `mod_assign_get_assignments` 拿 `duedate`、`intro`、`introattachments`，比解析网页稳定 | `collector/session.py: moodle_login`，`connectors/moodle.py` 的 WS 优先、网页回退；fake_moodle 模拟了这几个接口 |
| [crossbario/autobahn-testsuite](https://github.com/crossbario/autobahn-testsuite) | 用 Docker 镜像跑 fuzzingclient；排除 12.*、13.*（permessage-deflate） | `deploy/autobahn/fuzzingclient.json`、`devtools/autobahn_echo.py` |
| Flutter 官方自适应布局指南、Immich / Spotube 等 Material 3 应用 | 按窗口宽度（< 600 / 600–1279 / ≥ 1280）切换底部导航栏、侧边导航栏、展开侧栏 + 列表-详情；`ColorScheme.fromSeed` 统一深浅色；滑动操作、空状态插画、下拉刷新 | `client/lib/features/shell/app_shell.dart`、`theme.dart`、`inbox_page.dart` |

说明：调研时 GitHub 网页访问受限，部分结论来自对这些项目的已有了解；引用具体字段名或函数名前请再核对一次源码。
