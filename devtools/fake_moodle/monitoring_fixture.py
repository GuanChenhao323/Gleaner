"""Small synthetic assignment surface for monitoring UI and protocol validation."""

from gleaner.net.http import Request, Response
from gleaner.net.http.message import Headers
from gleaner.net.http.server import HTTPServer, ServerConfig


class MonitoringFixture:
    def __init__(self) -> None:
        self.scenario = "normal"
        self.requests = []
        self.server = HTTPServer(self.handle, ServerConfig(host="127.0.0.1", port=0))

    async def handle(self, request: Request) -> Response:
        self.requests.append(request.path)
        if request.path == "/robots.txt":
            return Response(
                200,
                body=b"User-agent: *\nAllow: /",
                headers=Headers({"Content-Type": "text/plain"}),
            )
        if (
            self.scenario == "expired"
            or "MoodleSession=SYNTHETIC" not in request.headers.get("Cookie", "")
        ):
            return Response(
                200,
                body=b'<html><form id="login">Login</form></html>',
                headers=Headers({"Content-Type": "text/html"}),
            )
        if self.scenario == "unavailable":
            return Response(503, body=b"busy")
        text = "Read chapter 3" if self.scenario == "changed" else "Read chapter 2"
        body = f"""<html><body id="page-mod-assign-view"><div class="logininfo">
        <a href="/user/profile.php?id=42">Synthetic student</a><a href="/login/logout.php">Logout</a></div>
        <div class="page-header-headings"><h1>Test assignment</h1></div><main id="region-main">
        <div id="intro"><div class="no-overflow">{text}</div></div></main></body></html>"""
        return Response(
            200,
            body=body.encode(),
            headers=Headers({"Content-Type": "text/html; charset=utf-8"}),
        )
