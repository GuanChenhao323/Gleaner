import asyncio
import datetime
import ssl
from argparse import Namespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fake_moodle.monitoring_fixture import MonitoringFixture
from monitoring.run import Harness
from monitoring_helpers import cookie

from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import FetchPlan, MonitorError, SitePolicy
from gleaner.monitoring.transport import HTTPXTransport
from gleaner.net.http import Request
from gleaner.net.http.message import Headers


def certificate(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, False, True, False, False, True, True, False, False), critical=True
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_file, key_file)
    return server, ssl.create_default_context(cafile=str(cert_file))


@pytest.mark.parametrize("tls", [False, True])
async def test_real_loopback_transport_and_tls_sni(tmp_path, tls):
    fixture = MonitoringFixture()
    names = []
    verify = True
    if tls:
        context, verify = certificate(tmp_path)
        context.set_servername_callback(lambda sock, name, ctx: names.append(name))
        fixture.server.config.ssl_context = context
    await fixture.server.start()
    origin = f"{'https' if tls else 'http'}://localhost:{fixture.server.port}"
    policy = SitePolicy(origin=origin, local_test=True, host_gap_s=0.01)
    auth = AuthManager(policy)
    c = auth.create(1, "b")
    auth.import_cookies(
        c.auth_id,
        [cookie(value="SYNTHETIC", domain="localhost")],
        backend_epoch=auth.backend_epoch,
        expected_revision=0,
        request_id="i",
    )

    async def resolve_loopback(host, port):
        return ["127.0.0.1"]

    transport = HTTPXTransport(policy, auth, resolver=resolve_loopback, verify=verify)
    plan = FetchPlan("s", 1, c.generation, "c", origin + "/mod/assign/view.php?id=7", (1,))
    try:
        response = await transport.fetch(plan, await auth.acquire(c.auth_id))
        assert response.status == 200 and b"Read chapter 2" in response.body
        assert fixture.requests == ["/robots.txt", "/mod/assign/view.php"]
        if tls:
            assert names == ["localhost", "localhost"]
            untrusted = HTTPXTransport(policy, auth, resolver=resolve_loopback)
            try:
                with pytest.raises(MonitorError) as error:
                    await untrusted.fetch(plan, await auth.acquire(c.auth_id))
                assert error.value.code == "tls" and not error.value.retryable
            finally:
                await untrusted.close()
    finally:
        await transport.close()
        await fixture.server.close()


async def test_dns_is_inside_connect_deadline():
    async def slow(host, port):
        await asyncio.sleep(1)
        return ["1.1.1.1"]

    policy = SitePolicy()
    auth = AuthManager(policy)
    transport = HTTPXTransport(policy, auth, resolver=slow, connect_timeout=0.01)
    try:
        with pytest.raises(MonitorError, match="timeout"):
            await transport.fetch(
                FetchPlan("s", 1, None, "c", policy.origin + "/mod/assign/view.php?id=7", (1,)),
                None,
            )
    finally:
        await transport.close()


async def test_debug_harness_persistent_restart_and_receipt_report(tmp_path):
    import json

    args = Namespace(
        real=False,
        target="",
        database=str(tmp_path / "debug.db"),
        port=0,
        report=str(tmp_path / "report.jsonl"),
        duration=7800,
        chrome_version="synthetic",
        exit_on_finish=True,
    )
    first = Harness(args)
    await first.setup()
    source_id = first.source.source_id
    old_generation = first.context.generation
    await first.action({"action": "start"})
    task = asyncio.create_task(first.loop())
    try:
        async with asyncio.timeout(5):
            while not first.successes:
                await asyncio.sleep(0.05)
        await first.action({"action": "stop"})
        await task
        rows = [json.loads(line) for line in (tmp_path / "report.jsonl").read_text().splitlines()]
        observation = next(row for row in rows if row["record"] == "observation")
        assert observation["stub_receipt"]["applied"]
        assert observation["stub_receipt"]["state"] == "succeeded"
        assert observation["scheduled_at"] <= observation["started_at"]
        assert not rows[-1]["passed"]
    finally:
        task.cancel()
        await first.close()
    second = Harness(args)
    try:
        await second.setup()
        assert second.source.source_id == source_id
        assert second.context.generation > old_generation
        assert second.context.state == "unverified"
    finally:
        await second.close()


async def test_debug_input_origin_scope_and_secret_storage(tmp_path):
    import json

    args = Namespace(
        real=False,
        target="",
        database=str(tmp_path / "debug.db"),
        port=0,
        report=str(tmp_path / "report.jsonl"),
        duration=7800,
        chrome_version="synthetic",
        exit_on_finish=True,
    )
    harness = Harness(args)
    await harness.setup()
    host = harness.origin.removeprefix("http://")
    chrome_cookie = {
        "name": "MoodleSession",
        "value": "SYNTHETIC_PRIVATE_COOKIE",
        "domain": "127.0.0.1",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "hostOnly": True,
        "sameSite": "lax",
        "session": True,
    }
    body = json.dumps(
        {"action": "import", "cookies": [chrome_cookie, {"name": "unrelated", "value": "discard"}]}
    ).encode()
    headers = {
        "Host": host,
        "Origin": "https://evil.example",
        "X-Debug-Token": harness.token,
        "Content-Type": "application/json",
    }
    try:
        denied = await harness.handle(
            Request(method="POST", target="/control", body=body, headers=Headers(headers))
        )
        assert denied.status == 403
        headers["Origin"] = harness.origin
        accepted = await harness.handle(
            Request(method="POST", target="/control", body=body, headers=Headers(headers))
        )
        assert accepted.status == 200 and accepted.headers["Cache-Control"] == "no-store"
        assert len(harness.context.jar) == 1
        assert "SYNTHETIC_PRIVATE_COOKIE" not in json.dumps(harness.state())
        assert b"SYNTHETIC_PRIVATE_COOKIE" not in (tmp_path / "debug.db").read_bytes()
        assert "SYNTHETIC_PRIVATE_COOKIE" not in (tmp_path / "report.jsonl").read_text()
        navigation = await harness.handle(
            Request(
                target="/",
                method="GET",
                headers=Headers(
                    {
                        "Host": host,
                        "Sec-Fetch-Site": "cross-site",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Dest": "document",
                    }
                ),
            )
        )
        assert navigation.status == 200
    finally:
        await harness.close()
