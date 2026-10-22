import asyncio
import json

from gleaner.core.summarize import Summarizer
from gleaner.net.http import Headers, HTTPServer, Response, Router, ServerConfig

BODY = "各位同学：本学期期中考试将于11月9日至11月13日进行，具体考场安排请登录教务系统查询。" * 3


def test_disabled_without_full_config(monkeypatch):
    monkeypatch.setenv("GLEANER_LLM_API_KEY", "k")
    monkeypatch.delenv("GLEANER_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("GLEANER_LLM_MODEL", raising=False)
    assert not Summarizer().enabled


async def test_openai_compatible_call_and_fallback(monkeypatch):
    seen = {}
    router = Router()

    @router.route("POST", "/v1/chat/completions")
    async def chat(req):
        seen["auth"] = req.headers.get("Authorization")
        seen["model"] = req.json()["model"]
        content = json.dumps(
            {"title": "期中考试 11月9日开始", "summary": "11月9日至13日，考场见教务系统"}
        )
        return Response.json_body({"choices": [{"message": {"content": content}}]})

    @router.route("POST", "/slow/v1/chat/completions")
    async def slow(req):
        await asyncio.sleep(2)
        return Response(200, headers=Headers(), body=b"{}")

    srv = HTTPServer(router, ServerConfig(host="127.0.0.1", port=0))
    await srv.start()
    monkeypatch.setenv("GLEANER_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("GLEANER_LLM_MODEL", "some-model")
    monkeypatch.setenv("GLEANER_LLM_BASE_URL", f"http://127.0.0.1:{srv.port}/v1")
    s = await Summarizer().summarize("关于期中考试安排的通知", BODY)
    assert s.by == "llm" and s.title.startswith("期中考试")
    assert seen == {"auth": "Bearer sk-test", "model": "some-model"}
    # 超时退回规则提取
    monkeypatch.setenv("GLEANER_LLM_BASE_URL", f"http://127.0.0.1:{srv.port}/slow")
    s = await Summarizer(timeout=0.3).summarize("关于期中考试安排的通知", BODY)
    assert s.by == "rule" and s.title == "期中考试安排"
    await srv.close()
