# ruff: noqa: F811  （stack 是从 test_e2e 导入的 pytest fixture）

"""采集网络层的协议合规：Cookie 存储模型（RFC 6265 §5.3）、robots.txt（RFC 9309）、
Retry-After（RFC 9110 §10.2.3）、逐跳重定向限速与跨源凭证（RFC 9110 §15.4）、网关 Host 白名单。"""

import asyncio
import time
from collections.abc import Callable

import pytest
from test_e2e import stack  # noqa: F401

from gleaner.collector.fetcher import (
    Fetcher,
    FetchError,
    RobotsRules,
    parse_retry_after,
    parse_robots,
)
from gleaner.gateway.app import _host_allowed, _origin_allowed

from gleaner.net.http import CookieJar, Headers, HTTPClient
from gleaner.net.http.cookies import MAX_PER_DOMAIN, default_path, parse_cookie_date, path_match

# ---- Cookie ----------------------------------------------------------------------


def test_cookie_domain_must_domain_match_request_host():
    jar = CookieJar()
    # 给别的域、上级的顶级域、IP 的“上级”种 Cookie：整条忽略（§5.3 第 6 步）
    assert not jar.set_from_header("a=1; Domain=evil.com", "moodle.must.edu.mo")
    assert not jar.set_from_header("a=1; Domain=mo", "moodle.must.edu.mo")
    assert not jar.set_from_header("a=1; Domain=0.1", "10.0.0.1")
    assert len(jar) == 0
    # 合法的上级域：子域也能收到
    assert jar.set_from_header("sid=1; Domain=.must.edu.mo; Path=/", "moodle.must.edu.mo")
    assert jar.header_for("login.must.edu.mo", "/", True) == "sid=1"
    assert jar.header_for("must.edu.mo.evil.com", "/", True) is None
    # 没有 Domain：只回给原主机
    jar.set_from_header("h=2; Path=/", "moodle.must.edu.mo")
    assert jar.header_for("sub.moodle.must.edu.mo", "/", True) == "sid=1"
    # 单标签主机（localhost）可以把 Domain 设成自己
    assert jar.set_from_header("l=1; Domain=localhost", "localhost")


def test_cookie_secure_controls_and_limits():
    jar = CookieJar()
    assert not jar.set_from_header("s=1; Secure", "a.example.com", "/", secure_request=False)
    assert jar.set_from_header("s=1; Secure", "a.example.com", "/", secure_request=True)
    # 明文响应不能覆盖 Secure Cookie
    assert not jar.set_from_header("s=evil", "a.example.com", "/", secure_request=False)
    assert jar.header_for("a.example.com", "/", True) == "s=1"
    assert jar.header_for("a.example.com", "/", False) is None
    # 控制字符、空名称、无 =
    for bad in ("x=a\x01b", "=v", "novalue", "bad\nname=1"):
        assert not jar.set_from_header(bad, "a.example.com")
    # 属性：SameSite 保存；Max-Age 不合法时忽略，≤0 立即删除
    jar.set_from_header("k=1; SameSite=Lax; Max-Age=abc", "a.example.com")
    assert next(c for c in jar.to_list() if c["name"] == "k")["same_site"] == "lax"
    jar.set_from_header("k=1; Max-Age=0", "a.example.com")
    assert "k=" not in (jar.header_for("a.example.com", "/", True) or "")
    # 每个域有上限，淘汰最早的
    for i in range(MAX_PER_DOMAIN + 5):
        jar.set_from_header(f"n{i}=v", "b.example.com")
    names = [c["name"] for c in jar.to_list() if c["domain"] == "b.example.com"]
    assert len(names) == MAX_PER_DOMAIN and "n0" not in names
    # 旧格式会话（没有 same_site、created）照常恢复
    old = CookieJar.from_list([{"name": "a", "value": "1", "domain": "x.com", "path": "/"}])
    assert old.header_for("x.com", "/", True) == "a=1"


def test_cookie_paths_follow_rfc6265():
    assert default_path("/course/view.php") == "/course"
    assert default_path("/view.php") == "/"
    assert default_path("") == "/"
    assert default_path("/a/b/?q=/x/y") == "/a/b"
    assert path_match("/foo/bar", "/foo") and path_match("/foo", "/foo")
    assert not path_match("/foobar", "/foo")
    assert path_match("/foo/bar", "/foo/") and not path_match("/foo", "/foo/")
    jar = CookieJar()
    jar.set_from_header("a=1; Path=/x", "h.com")
    jar.set_from_header("b=2; Path=/x/y", "h.com")
    assert jar.header_for("h.com", "/x/y/z?q=1", True) == "b=2; a=1"  # 路径长的在前


@pytest.mark.parametrize(
    "expiry",
    [
        "Thu, 01-Jan-1970 00:00:01 GMT",
        "Thursday, 01-Jan-70 00:00:01 GMT",
        "Thu Jan 1 00:00:01 1970",
    ],
)
def test_cookie_historical_expires_deletes_instead_of_retaining_an_empty_session(expiry):
    jar = CookieJar()
    jar.set_from_header("SID=OLD; Domain=.youtube.com; Path=/; Secure", "www.youtube.com")
    jar.set_from_header(
        f"SID=; Domain=.youtube.com; Path=/; Expires={expiry}; Secure", "www.youtube.com"
    )
    assert len(jar) == 0 and jar.header_for("www.youtube.com", "/", True) is None


def test_cookie_max_age_still_overrides_historical_expires():
    jar = CookieJar()
    jar.set_from_header(
        "SID=LIVE; Expires=Thu, 01-Jan-1970 00:00:01 GMT; Max-Age=600; Secure", "www.youtube.com"
    )
    assert jar.header_for("www.youtube.com", "/", True) == "SID=LIVE"


@pytest.mark.parametrize(
    "value",
    [
        "31 Apr 2026 00:00:00 GMT",
        "01 Jan 1600 00:00:00 GMT",
        "00 Jan 2026 00:00:00 GMT",
        "01 Jan 2026 24:00:00 GMT",
        "01 Jan 2026 00:00:60 GMT",
        "Jan 2026 00:00:00 GMT",
    ],
)
def test_cookie_date_rejects_invalid_or_incomplete_dates(value):
    assert parse_cookie_date(value) is None


def test_cookie_date_two_digit_year_boundary_and_case_insensitive_month():
    from datetime import UTC, datetime

    assert (
        parse_cookie_date("01-jAn-69 00:00:00 GMT") == datetime(2069, 1, 1, tzinfo=UTC).timestamp()
    )
    assert parse_cookie_date("01-JAN-70 00:00:00 GMT") == 0


# ---- robots.txt ------------------------------------------------------------------


def test_robots_groups_wildcards_and_longest_match():
    text = """
    User-agent: *
    Disallow: /private
    Disallow: /*.pdf$
    Allow: /private/public
    Crawl-delay: 3

    User-agent: otherbot
    Disallow: /
    """
    r = parse_robots(text)
    assert not r.allowed("/private/x") and r.allowed("/private/public/a")
    assert not r.allowed("/files/a.pdf") and r.allowed("/files/a.pdf?download=1")
    assert r.allowed("/course/view.php") and r.crawl_delay == 3
    assert r.allowed("/robots.txt")
    # 有本程序专属组时只用它，不再叠加 * 组
    mine = parse_robots("User-agent: *\nDisallow: /\n\nUser-agent: Gleaner\nDisallow: /admin\n")
    assert mine.allowed("/course") and not mine.allowed("/admin/x")
    # 连续 user-agent 行属于同一组；Allow 与 Disallow 等长时 Allow 优先
    g = parse_robots("User-agent: a\nUser-agent: gleaner\nDisallow: /x\nAllow: /x\n")
    assert g.allowed("/x")
    # 空 Disallow 不限制；组外规则忽略
    assert parse_robots("Disallow: /\nUser-agent: *\nDisallow:\n").allowed("/anything")
    assert not RobotsRules(disallow_all=True).allowed("/x")


# ---- Retry-After -----------------------------------------------------------------


def test_parse_retry_after_seconds_and_http_date():
    now = 1_700_000_000.0
    assert parse_retry_after("120", now) == 120
    assert parse_retry_after("Tue, 14 Nov 2023 22:23:20 GMT", now) == 600
    assert parse_retry_after("Tue, 14 Nov 2023 22:00:00 GMT", now) == 0  # 已过去
    assert parse_retry_after("soon", now) is None and parse_retry_after(None) is None
    assert parse_retry_after("-5", now) is None


# ---- 用真实套接字的抓取测试 ------------------------------------------------------

Handler = Callable[[str, dict[str, str]], bytes]


async def serve(handler: Handler, log: list) -> tuple[asyncio.Server, int]:
    async def conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode("latin-1").split("\r\n")
                method, target, _ = lines[0].split(" ", 2)
                headers = {}
                for ln in lines[1:]:
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        headers[k.strip().lower()] = v.strip()
                log.append((time.monotonic(), method, target, headers))
                writer.write(handler(target, headers))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    srv = await asyncio.start_server(conn, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


def resp(status: str, headers: dict[str, str] | None = None, body: bytes = b"") -> bytes:
    h = {"Content-Length": str(len(body)), **(headers or {})}
    return (
        f"HTTP/1.1 {status}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n"
    ).encode() + body


async def test_robots_rules_and_unreachable_robots_are_enforced():
    log: list = []
    robots = b"User-agent: *\nDisallow: /*.pdf$\nAllow: /secret/ok\nDisallow: /secret\n"

    def handler(target: str, headers: dict) -> bytes:
        if target == "/robots.txt":
            return resp("200 OK", {"Content-Type": "text/plain"}, robots)
        return resp("200 OK", body=b"ok")

    srv, port = await serve(handler, log)
    f = Fetcher(HTTPClient(), min_interval=0)
    base = f"http://127.0.0.1:{port}"
    try:
        assert (await f.fetch(base + "/secret/ok/page")).status == 200
        for path in ("/secret/x", "/doc/a.pdf"):
            with pytest.raises(FetchError) as ei:
                await f.fetch(base + path)
            assert ei.value.kind == "robots"
        assert [t for _, _, t, _ in log].count("/robots.txt") == 1  # 有缓存
    finally:
        await f.close()
        srv.close()

    # robots.txt 返回 5xx：视为全部禁止，不访问页面
    log2: list = []
    srv, port = await serve(lambda t, h: resp("503 Service Unavailable"), log2)
    f = Fetcher(HTTPClient(), min_interval=0)
    try:
        with pytest.raises(FetchError) as ei:
            await f.fetch(f"http://127.0.0.1:{port}/page")
        assert ei.value.kind == "robots"
        assert [t for _, _, t, _ in log2] == ["/robots.txt"]
    finally:
        await f.close()
        srv.close()


async def test_retry_after_is_honoured_not_truncated():
    log: list = []
    srv, port = await serve(lambda t, h: resp("429 Too Many Requests", {"Retry-After": "600"}), log)
    f = Fetcher(HTTPClient(), min_interval=0, respect_robots=False)
    url = f"http://127.0.0.1:{port}/x"
    try:
        t0 = time.monotonic()
        with pytest.raises(FetchError) as ei:
            await f.fetch(url)
        assert ei.value.retry_after == 600 and time.monotonic() - t0 < 5  # 不在本次里干等，也不缩短
        # 同一主机在 Retry-After 之前不再发请求
        with pytest.raises(FetchError) as ei:
            await f.fetch(url)
        assert ei.value.retry_after and ei.value.retry_after > 590
        assert len(log) == 1
    finally:
        await f.close()
        srv.close()

    # 短的 Retry-After：在本次检查里等够再重试
    log2: list = []
    calls = {"n": 0}

    def flaky(target: str, headers: dict) -> bytes:
        calls["n"] += 1
        return resp("503 Busy", {"Retry-After": "1"}) if calls["n"] == 1 else resp("200 OK")

    srv, port = await serve(flaky, log2)
    f = Fetcher(HTTPClient(), min_interval=0, respect_robots=False)
    try:
        assert (await f.fetch(f"http://127.0.0.1:{port}/y")).status == 200
        assert log2[1][0] - log2[0][0] >= 0.95
    finally:
        await f.close()
        srv.close()


async def test_redirect_hops_are_paced_and_credentials_not_forwarded():
    log_a: list = []
    log_b: list = []
    srv_b, port_b = await serve(lambda t, h: resp("200 OK", body=b"final"), log_b)

    def a(target: str, headers: dict) -> bytes:
        if target == "/start":
            return resp("302 Found", {"Location": "/middle"})
        if target == "/middle":
            return resp("302 Found", {"Location": f"http://127.0.0.1:{port_b}/end"})
        return resp("404 Not Found")

    srv_a, port_a = await serve(a, log_a)
    f = Fetcher(HTTPClient(), min_interval=0.3, respect_robots=False)
    try:
        r = await f.fetch(
            f"http://127.0.0.1:{port_a}/start",
            headers={"Authorization": "Bearer secret", "X-Trace": "1"},
            etag='"v1"',
        )
        assert r.status == 200 and r.body == b"final"
        assert len(r.history) == 2 and r.url.endswith("/end")
        # 同主机的两跳之间也遵守最小间隔
        assert log_a[1][0] - log_a[0][0] >= 0.28
        # 同源跳转保留凭证；跨源（端口不同）去掉凭证与条件请求头
        assert log_a[1][3].get("authorization") == "Bearer secret"
        assert "if-none-match" not in log_a[1][3]
        hdrs = log_b[0][3]
        assert "authorization" not in hdrs and hdrs.get("x-trace") == "1"
    finally:
        await f.close()
        srv_a.close()
        srv_b.close()

    # 跳转次数上限
    loop_log: list = []
    srv, port = await serve(lambda t, h: resp("302 Found", {"Location": "/again"}), loop_log)
    f = Fetcher(HTTPClient(), min_interval=0, respect_robots=False, max_redirects=3)
    try:
        with pytest.raises(FetchError):
            await f.fetch(f"http://127.0.0.1:{port}/again")
        assert len(loop_log) == 4
    finally:
        await f.close()
        srv.close()


async def test_http_client_strips_credentials_on_cross_origin_redirect():
    log_b: list = []
    srv_b, port_b = await serve(lambda t, h: resp("200 OK"), log_b)
    srv_a, port_a = await serve(
        lambda t, h: resp("307 Temporary Redirect", {"Location": f"http://127.0.0.1:{port_b}/"}),
        [],
    )
    try:
        async with HTTPClient() as c:
            r = await c.get(
                f"http://127.0.0.1:{port_a}/", headers={"Authorization": "x", "Cookie": "a=1"}
            )
        assert r.status == 200
        assert "authorization" not in log_b[0][3] and "cookie" not in log_b[0][3]
    finally:
        srv_a.close()
        srv_b.close()


# ---- 网关 Host 与 CORS 白名单 -----------------------------------------------------


def test_gateway_host_and_origin_allow_lists():
    allowed = ("localhost", "127.0.0.1", "[::1]")
    assert _host_allowed("localhost:8080", allowed) and _host_allowed("127.0.0.1", allowed)
    assert _host_allowed("[::1]:8080", allowed)
    assert not _host_allowed("attacker.example:8080", allowed)
    assert not _host_allowed("", allowed)
    assert _host_allowed("anything", ())  # 未配置时不检查
    origins = ("http://localhost:*", "https://app.example.edu")
    assert _origin_allowed("http://localhost:53122", origins)
    assert _origin_allowed("https://app.example.edu", origins)
    assert not _origin_allowed("http://localhost.evil.com:80", origins)
    assert not _origin_allowed("https://localhost:443", origins)  # 协议不同
    assert not _origin_allowed("null", origins)


async def test_gateway_rejects_foreign_host_header(stack):
    """真实网关：配置 Host 白名单后，伪造 Host（DNS 重绑定）返回 400，本机 Host 正常转发。"""
    import dataclasses

    from gleaner.services import start_gateway

    cfg = dataclasses.replace(
        stack["cfg"],
        allowed_hosts="localhost,127.0.0.1",
        cors_origins="http://localhost:*",
    )
    gw = await start_gateway(cfg, host="127.0.0.1", port=0, check_interval=0.2)
    port = gw.info["port"]
    try:
        async with HTTPClient() as c:
            ok = await c.get(f"http://127.0.0.1:{port}/api/health")
            assert ok.status == 200
            bad = await c.get(
                f"http://127.0.0.1:{port}/api/health", headers={"Host": f"attacker.example:{port}"}
            )
            assert bad.status == 400 and bad.json()["error"] == "bad_host"
            pre = await c.request(
                "OPTIONS",
                f"http://127.0.0.1:{port}/api/feed",
                headers={"Origin": "http://localhost:5173"},
            )
            assert pre.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
            assert "PATCH" in (pre.headers.get("Access-Control-Allow-Methods") or "")
            other = await c.request(
                "OPTIONS",
                f"http://127.0.0.1:{port}/api/feed",
                headers={"Origin": "https://evil.example"},
            )
            assert other.headers.get("Access-Control-Allow-Origin") is None
    finally:
        await gw.close()


async def test_client_falls_back_to_next_resolved_address(monkeypatch):
    """解析出多个地址时依次尝试：localhost 的 ::1 没有服务时退到 127.0.0.1（RFC 8305 第 4 节的顺序尝试）。"""
    from gleaner.net import egress

    monkeypatch.setenv("GLEANER_EGRESS_ALLOW_PRIVATE", "1")
    srv, port = await serve(lambda t, h: resp("200 OK", body=b"v4"), [])
    real = egress.checked_addresses

    async def both(host, p, resolver=None):  # 模拟 ::1 排在前面、但只有 IPv4 在监听
        return ["::1", "127.0.0.1"] if host == "dual.test" else await real(host, p, resolver)

    monkeypatch.setattr("gleaner.net.http.client.checked_addresses", both)
    try:
        async with HTTPClient(egress_guard=True) as c:
            r = await c.get(f"http://dual.test:{port}/")
        assert r.status == 200 and r.body == b"v4"
    finally:
        srv.close()


async def test_static_assets_revalidate_except_canvaskit(tmp_path):
    """Flutter 的 assets/ 每次构建同名不同内容：必须协商缓存；只有 canvaskit/ 可以长缓存。"""
    from gleaner.net.http import Request
    from gleaner.net.http.static import StaticFiles

    (tmp_path / "assets" / "fonts").mkdir(parents=True)
    (tmp_path / "canvaskit").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "assets" / "fonts" / "MaterialIcons-Regular.otf").write_bytes(b"font")
    (tmp_path / "canvaskit" / "canvaskit.wasm").write_bytes(b"wasm")
    sf = StaticFiles(tmp_path)

    async def cache_of(path: str) -> str:
        r = await sf(Request("GET", path, "HTTP/1.1", Headers({"Host": "x"})))
        assert r.status == 200
        return r.headers.get("Cache-Control") or ""

    assert await cache_of("/index.html") == "no-cache"
    assert await cache_of("/assets/fonts/MaterialIcons-Regular.otf") == "no-cache"
    assert (await cache_of("/canvaskit/canvaskit.wasm")).startswith("public, max-age=")
