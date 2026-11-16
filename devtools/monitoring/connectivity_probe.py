"""Manual anonymous MUST connectivity check; never run from pytest/CI.

Run: .venv/bin/python -m devtools.monitoring.connectivity_probe
Only GET /robots.txt, without credentials or following redirects.
"""

from __future__ import annotations

import asyncio
import json

from gleaner.monitoring.auth import AuthManager
from gleaner.monitoring.models import SitePolicy
from gleaner.monitoring.transport import HTTPXTransport, resolve


async def main() -> None:
    policy = SitePolicy()
    transport = HTTPXTransport(policy, AuthManager(policy))
    try:
        system = await resolve(policy.host, 443)
        pinned, _ = await transport._ip(policy.origin + "/robots.txt")
        # Exercise the actual monitoring request path, preserving TLS, limits and pacing.
        async with asyncio.timeout(30):
            status, _, body = await transport._one(
                policy.origin + "/robots.txt", None, kind="robots"
            )
        print(
            json.dumps(
                {
                    "system_dns": system,
                    "checked_destination": pinned,
                    "http_status": status,
                    "body_bytes": len(body),
                    "tls_verified": True,
                    "credentials_sent": False,
                    "redirect_followed": False,
                },
                indent=2,
            )
        )
    finally:
        await transport.close()


if __name__ == "__main__":
    asyncio.run(main())
