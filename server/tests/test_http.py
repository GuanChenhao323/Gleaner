import asyncio
import gzip

import pytest
import requests

from gleaner.net.http import (
    Headers,
    HTTPClient,
    HTTPError,
    HTTPParser,
    HTTPServer,
    ParseError,
    Request,
    Response,
    Router,
    ServerConfig,
    http_date,
    not_modified,
    parse_http_date,
    parse_range,
)

RAW = b"GET /a?x=1 HTTP/1.1\r\nHost: h\r\nX-Y: z\r\n\r\n"


def test_parse_simple():
    [req] = HTTPParser().feed(RAW)
    assert req.method == "GET" and req.path == "/a" and req.query == {"x": "1"}
    assert req.headers["x-y"] == "z" and req.keep_alive


def test_parse_byte_by_byte_and_pipelined():
    p = HTTPParser()
    data = RAW + b"POST /b HTTP/1.1\r\nHost: h\r\nContent-Length: 5\r\n\r\nhello" + RAW
    out = []
    for i in range(len(data)):
        out += p.feed(data[i : i + 1])
    assert [r.method for r in out] == ["GET", "POST", "GET"]
    assert out[1].body == b"hello"


def test_parse_chunked_with_ext_and_trailer():
    data = (
        b"POST / HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\n"
        b"5;ext=1\r\nhello\r\n6\r\n world\r\n0\r\nX-T: 1\r\n\r\n"
    )
    p = HTTPParser()
    msgs = []
    for i in range(0, len(data), 3):
        msgs += p.feed(data[i : i + 3])
    assert msgs[0].body == b"hello world"
    assert p.idle


@pytest.mark.parametrize(
    "raw,status",
    [
        (b"GET / HTTP/1.1\r\n\r\n", 400),  # 缺 Host
        (b"GET / HTTP/2.0\r\nHost: h\r\n\r\n", 505),
        (b"GET /\r\nHost: h\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost : h\r\n\r\n", 400),
        (b"GET / HTTP/1.1\r\nHost: h\r\n folded\r\n\r\n", 400),
        (
            b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: 3\r\nTransfer-Encoding: chunked\r\n\r\n",
            400,
        ),
        (b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: 3, 4\r\n\r\n", 400),
        (b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: -1\r\n\r\n", 400),
        (b"POST / HTTP/1.1\r\nHost: h\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n", 400),
    ],
)
def test_parse_malformed(raw, status):
    with pytest.raises(ParseError) as ei:
        HTTPParser().feed(raw)
    assert ei.value.status == status


def test_header_limit():
    p = HTTPParser(max_header_bytes=100)
    with pytest.raises(ParseError) as ei:
        p.feed(b"GET / HTTP/1.1\r\nHost: h\r\nX: " + b"a" * 200)
    assert ei.value.status == 431


def test_body_limit():
    with pytest.raises(ParseError) as ei:
        HTTPParser(max_body_bytes=10).feed(
            b"POST / HTTP/1.1\r\nHost: h\r\nContent-Length: 11\r\n\r\n"
        )
    assert ei.value.status == 413


def test_response_head_and_eof_body():
    p = HTTPParser("response")
    p.expect_response("HEAD")
    p.expect_response("GET")
    msgs = p.feed(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nHTTP/1.0 200 OK\r\n\r\nabc")
    assert len(msgs) == 1 and msgs[0].body == b""
    msgs = p.feed(b"def")
    assert msgs == []
    [m] = p.feed_eof()
    assert m.body == b"abcdef"


def test_response_304_no_body():
    p = HTTPParser("response")
    p.expect_response("GET")
    [m] = p.feed(b'HTTP/1.1 304 Not Modified\r\nETag: "x"\r\nContent-Length: 99\r\n\r\n')
    assert m.status == 304 and m.body == b""


def test_eof_mid_message():
    p = HTTPParser()
    p.feed(b"GET / HTTP/1.1\r\nHo")
    with pytest.raises(ParseError):
        p.feed_eof()


def test_dates_roundtrip():
    s = http_date(784111777)
    assert s == "Sun, 06 Nov 1994 08:49:37 GMT"
    assert parse_http_date(s) == 784111777
    assert parse_http_date("Sunday, 06-Nov-94 08:49:37 GMT") == 784111777
    assert parse_http_date("Sun Nov  6 08:49:37 1994") == 784111777


def test_conditional_and_range():
    req = Request("GET", "/", headers=Headers({"If-None-Match": 'W/"a", "b"'}))
    assert not_modified(req, '"a"', None)
    assert not not_modified(req, '"c"', None)
    req = Request("GET", "/", headers=Headers({"If-Modified-Since": http_date(1000)}))
    assert not_modified(req, None, 1000.5)
    assert not not_modified(req, None, 2000)
    assert parse_range("bytes=0-9", 100) == (0, 9)
    assert parse_range("bytes=90-", 100) == (90, 99)
    assert parse_range("bytes=-10", 100) == (90, 99)
    assert parse_range("bytes=100-", 100) == "invalid"
    assert parse_range("bytes=0-1,3-4", 100) == "invalid"


# ---- 服务端 + 客户端集成 ----------------------------------------------------


async def make_server(**cfg):
    router = Router()

    @router.route("GET", "/hello/{name}")
    async def hello(req):
        return Response.text_body(f"hi {req.params['name']}")

    @router.route("POST", "/echo")
    async def echo(req):
        return Response(
            200, headers=Headers({"Content-Type": "application/octet-stream"}), body=req.body
        )

    @router.route("GET", "/big")
    async def big(req):
        return Response.text_body("x" * 5000)

    @router.route("GET", "/stream")
    async def stream(req):
        async def gen():
            for i in range(3):
                yield f"part{i};".encode()
                await asyncio.sleep(0)

        return Response(200, headers=Headers({"Content-Type": "text/plain"}), stream=gen())

    @router.route("GET", "/etag")
    async def etag(req):
        h = Headers({"ETag": '"v1"'})
        if not_modified(req, '"v1"', None):
            return Response(304, headers=h)
        return Response(200, headers=h, body=b"content")

    srv = HTTPServer(router, ServerConfig(host="127.0.0.1", port=0, **cfg))
    await srv.start()
    return srv


async def test_client_keepalive_reuse_and_routes():
    srv = await make_server()
    base = f"http://127.0.0.1:{srv.port}"
    async with HTTPClient() as c:
        r1 = await c.get(base + "/hello/ann")
        r2 = await c.post(base + "/echo", body=b"\x00\x01data")
        r3 = await c.get(base + "/missing")
        r4 = await c.request("PUT", base + "/echo")
        assert r1.text() == "hi ann"
        assert r2.body == b"\x00\x01data"
        assert r3.status == 404
        assert r4.status == 405 and "POST" in r4.headers["Allow"]
        assert c.stats.connections_opened == 1
        assert c.stats.connections_reused == 3
    await srv.close()


async def test_gzip_chunked_and_conditional():
    srv = await make_server()
    base = f"http://127.0.0.1:{srv.port}"
    async with HTTPClient() as c:
        r = await c.get(base + "/big")
        assert r.headers.get("Content-Encoding") == "gzip" and r.text() == "x" * 5000
        r = await c.get(base + "/stream")
        assert r.headers.get("Transfer-Encoding") == "chunked" and r.body == b"part0;part1;part2;"
        r = await c.get(base + "/etag")
        assert r.status == 200
        r = await c.get(base + "/etag", headers={"If-None-Match": r.headers["ETag"]})
        assert r.status == 304 and r.body == b""
    await srv.close()


async def test_interop_with_requests_library():
    srv = await make_server()
    base = f"http://127.0.0.1:{srv.port}"

    def run():
        with requests.Session() as s:
            a = s.get(base + "/big")
            b = s.post(base + "/echo", data=b"abc")
            c = s.get(base + "/stream")
            return a.text, b.content, c.text

    a, b, c = await asyncio.to_thread(run)
    assert a == "x" * 5000 and b == b"abc" and c == "part0;part1;part2;"
    await srv.close()


async def test_raw_split_writes_and_malformed():
    srv = await make_server()
    r, w = await asyncio.open_connection("127.0.0.1", srv.port)
    for piece in (b"GET /hel", b"lo/x HTTP/1.1\r\nHo", b"st: a\r\n", b"\r\n"):
        w.write(piece)
        await w.drain()
        await asyncio.sleep(0.01)
    data = await asyncio.wait_for(r.readuntil(b"hi x"), 2)
    assert b"200 OK" in data
    w.write(b"BAD LINE\r\n\r\n")
    await w.drain()
    rest = await asyncio.wait_for(r.read(), 2)
    assert b"400" in rest
    w.close()
    await srv.close()


async def test_idle_and_header_timeout():
    srv = await make_server(keepalive_timeout=0.2, header_timeout=0.2)
    r, w = await asyncio.open_connection("127.0.0.1", srv.port)
    w.write(b"GET /hello/a HTTP/1.1\r\nHost: x")  # 半条请求后停住
    await w.drain()
    data = await asyncio.wait_for(r.read(), 2)
    assert b"408" in data
    w.close()
    await srv.close()


async def test_client_timeouts_and_stale_retry():
    async def silent(reader, writer):
        await asyncio.sleep(5)

    s = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = s.sockets[0].getsockname()[1]
    async with HTTPClient(read_timeout=0.2) as c:
        with pytest.raises(HTTPError) as ei:
            await c.get(f"http://127.0.0.1:{port}/")
        assert ei.value.kind == "timeout"
    s.close()

    async with HTTPClient(connect_timeout=0.5) as c:
        with pytest.raises(HTTPError) as ei:
            await c.get("http://127.0.0.1:1/")
        assert ei.value.kind in ("connect", "timeout")

    # 服务器在一次响应后关闭 keep-alive 连接：客户端应透明重试
    count = 0

    async def once(reader, writer):
        nonlocal count
        count += 1
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    s = await asyncio.start_server(once, "127.0.0.1", 0)
    port = s.sockets[0].getsockname()[1]
    async with HTTPClient() as c:
        await c.get(f"http://127.0.0.1:{port}/")
        await asyncio.sleep(0.05)
        r = await c.get(f"http://127.0.0.1:{port}/")
        assert r.body == b"ok" and count == 2
    s.close()


def test_gzip_helper_sanity():
    assert gzip.decompress(gzip.compress(b"a")) == b"a"
