# 邮件协议：IMAP（含 IDLE）、SMTP（含 STARTTLS）、POP3

实现：`server/gleaner/net/mail/`（`base.py` 行式连接、`imap.py`、`smtp.py`、`pop3.py`、`mime.py`），
`server/gleaner/mailsvc/receiver.py`（收信长连接）、`sender.py`（代用户发信）。
测试：`server/tests/test_mail.py`（对 `devtools/fake_mail` 的自签名 STARTTLS、错误口令、451 重试、IDLE 推送、POP3 字节填充、中文标题与附件）、
`server/tests/test_e2e.py::test_mail_merge_and_send`（IDLE 收到 Moodle 提醒邮件后跨渠道合并、发信幂等）。

所有收发都基于 `asyncio.open_connection` 手写协议交互；只有 MIME 的解析与组装使用标准库 `email`（已获老师同意）。

## 1. 公共层

`LineConn`：按 CRLF 读行、读定长字面量、统一超时（默认 30 s），记录会话 transcript（口令一律打码，供演示与排错）。
错误统一为 `MailError(code, temporary)`；`temporary` 决定是否退避重试。

## 2. IMAP4rev1（RFC 3501）+ IDLE（RFC 2177）

```
连接(993 TLS) → * OK 问候 → CAPABILITY → LOGIN 或 AUTHENTICATE XOAUTH2 → EXAMINE INBOX（只读）
→ UID SEARCH UID n:* → UID FETCH (UID FLAGS BODY.PEEK[]) → IDLE … 收到 EXISTS → DONE → 回到 SEARCH
```

- 响应读取：一条响应可以包含任意个字面量 `{n}\r\n<n 字节>`（§4.3），读行后检查行尾是否为字面量标记，循环读取。
- 带标签的完成应答：`OK` 正常，`NO`/`BAD` 抛 `MailError`。
- `BODY.PEEK[]` 不会给邮件加 `\Seen`，不改变用户在其他客户端的已读状态（§6.4.5）。
- 增量同步：记录 `UIDVALIDITY` 与已处理的最大 UID；UIDVALIDITY 变化说明 UID 失效（§2.3.1.1），只从最新 20 封重新开始。
- IDLE：服务器推送 `EXISTS` / `EXPUNGE` / `RECENT` 时结束 IDLE（发 `DONE`）并拉取新邮件；
  最长 29 分钟后主动重新发起，避免服务器 30 分钟超时断开（RFC 2177 §3）。服务器不支持 IDLE 时每 60 s `NOOP` 轮询。
- 断线：指数退避 1 s → 300 s 加抖动重连；口令错误标记来源为“需要重新登录”并停止重试。

## 3. SMTP（RFC 5321）+ STARTTLS（RFC 3207）+ AUTH（RFC 4954）

```
220 问候 → EHLO → 250-STARTTLS … → STARTTLS → 220 → TLS 握手 → EHLO（必须重新 EHLO，§4.2）
→ AUTH PLAIN（或 LOGIN）→ 235 → MAIL FROM → RCPT TO（逐个，记录拒绝的收件人）→ DATA → 354 → 正文 + "." → 250 → QUIT
```

- 多行应答 `250-…` 继续、`250 …` 结束（§4.2）。
- DATA 点号转义：行首 `.` 前再加一个 `.`，统一 CRLF（§4.5.2）。
- 附件：`email.message.EmailMessage.add_attachment` 组装 multipart，Base64 编码；中文标题按 RFC 2047 编码。
- 重试：4xx 临时错误、网络错误按 `base × 2^i × [0.5, 1.5)` 退避，最多 4 次；5xx 永久错误直接失败。
- 防重复提交：每次发信带客户端生成的 `Idempotency-Key`；`sent_mails(user_id, idempotency_key)` 唯一约束；
  Message-ID 由 `uuid5(user, key)` 生成，同一键永远相同。重复提交直接返回第一次的结果，不会发出第二封。

### 平台发信账号

注册验证码、可选的每日摘要邮件、运维告警都经平台自己的账号发送（`mailsvc/sender.py: send_platform_mail`），
配置为 `GLEANER_PLATFORM_SMTP_HOST / PORT / SECURITY / USER / PASS` 与 `GLEANER_PLATFORM_MAIL_FROM`，同样走上面的 SMTP 实现与退避重试。

## 4. POP3（RFC 1939）

`+OK` 问候 → `USER` / `PASS` → `STAT` → `UIDL`（跨会话稳定的唯一 ID，§7）→ 对未见过的 UID `RETR` → `QUIT`。
多行应答以单独一行 `.` 结束，行首 `..` 还原为 `.`。默认每 120 s 轮询；记住最近 2000 个 UIDL。

## 5. 邮件 → 事项

`mail_snapshot()`：解析多层 multipart、Base64 / Quoted-Printable、RFC 2047 标题，提取纯文本（HTML 邮件转文本）与链接。
Moodle 提醒邮件里有 `/mod/assign/view.php?id=N` 链接时，生成别名键 `url:/mod/assign/view.php?id=N`，
业务服务据此把邮件合并到课程页上的同一作业（只增加 `channels`，不新增事项）。
数据最少化：只保存标题、发件人、正文前 5000 字与链接，不保存附件内容。

## 6. 本地测试服务器

- `devtools/fake_mail/server.py`：内存 SMTP（STARTTLS 自签名证书、AUTH PLAIN/LOGIN、可注入 451）、IMAP（含 IDLE）、POP3。
- docker-compose dev profile：GreenMail（SMTP 3025 / IMAP 3143 / POP3 3110，无 TLS）。
