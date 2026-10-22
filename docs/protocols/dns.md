# DNS 解析器（RFC 1035）

实现：`server/gleaner/net/dns/resolver.py`。测试：`server/tests/test_dns.py`（本地假 DNS 服务器：丢包重试、CNAME、NXDOMAIN 负缓存、全部超时、压缩指针循环、截断报文）。

## 报文

| 部分 | 内容 |
| --- | --- |
| 头部（§4.1.1） | ID(16) · 标志：QR、Opcode、AA、TC、RD=1、RA、RCODE · QD/AN/NS/AR 计数 |
| 问题（§4.1.2） | QNAME（长度前缀标签，以 0 结束）· QTYPE · QCLASS=IN |
| 资源记录（§4.1.3） | NAME · TYPE · CLASS · TTL · RDLENGTH · RDATA（A、AAAA、CNAME、NS 解析为文本） |

名字压缩（§4.1.4）：标签首字节高两位为 `11` 时是 14 位偏移指针；限制最多 64 次跳转并检查越界，防止恶意报文造成死循环。

## 查询流程

1. 本机 hosts 文件命中则直接返回。
2. 缓存命中（按 TTL 过期；NXDOMAIN 按 SOA 最小 TTL 负缓存，RFC 2308）。
3. UDP 发送到第 `attempt % N` 个服务器，超时 `timeout × 2^attempt`，最多 3 次；响应 ID 不匹配视为无效。
4. TC 位置位时改用 TCP，报文前加 2 字节长度（§4.2.2）。
5. 跟随 CNAME 链最多 8 跳。

服务器列表来自 `GLEANER_DNS_SERVERS` 或 `/etc/resolv.conf`。采集引擎在 `GLEANER_USE_OWN_DNS=1` 时把解析器注入 HTTP 客户端。
