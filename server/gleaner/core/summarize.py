"""大模型摘要（P2）：经自研 HTTP 客户端调用，超时或失败回退到规则提取。

配置（环境变量）。默认使用 OpenAI 兼容接口（/v1/chat/completions），以便部署在国内云服务器时
接入国内服务商；三项都配置后才启用，否则一律走规则提取：
- GLEANER_LLM_BASE_URL：服务商接口地址，例如 https://<服务商域名>（不含 /v1）
- GLEANER_LLM_MODEL：模型名
- GLEANER_LLM_API_KEY：密钥
- GLEANER_LLM_PROVIDER：openai（默认）或 anthropic
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass

from ..net.http import HTTPClient, HTTPError
from .extract import clean_title, summarize

log = logging.getLogger(__name__)

PROMPT = (
    "你是校园通知整理助手。根据下面的通知原文，输出 JSON："
    '{"title": "不超过 20 字的一句话标题", "summary": "不超过 3 行的摘要，含日期、地点、适用对象"}。'
    "不要编造原文没有的信息。\n\n原文：\n"
)


@dataclass
class Summary:
    title: str
    summary: str
    by: str  # rule / llm


class Summarizer:
    def __init__(self, client: HTTPClient | None = None, timeout: float = 8.0) -> None:
        self.provider = os.environ.get("GLEANER_LLM_PROVIDER", "openai")
        self.api_key = os.environ.get("GLEANER_LLM_API_KEY", "")
        self.model = os.environ.get("GLEANER_LLM_MODEL", "")
        self.base = os.environ.get("GLEANER_LLM_BASE_URL", "").rstrip("/").removesuffix("/v1")
        self.timeout = timeout
        self.client = client or HTTPClient(read_timeout=timeout, per_host_limit=4)
        self.sem = asyncio.Semaphore(4)
        self.failures = 0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.model and self.base)

    def rule(self, title: str, body: str) -> Summary:
        return Summary(clean_title(title), summarize(body), "rule")

    async def summarize(self, title: str, body: str) -> Summary:
        base = self.rule(title, body)
        if not self.enabled or len(body) < 80:
            return base
        try:
            async with self.sem:
                text = await asyncio.wait_for(
                    self._call(f"标题：{title}\n{body[:4000]}"), self.timeout
                )
            data = json.loads(text[text.find("{") : text.rfind("}") + 1])
            return Summary(
                str(data.get("title") or base.title)[:40],
                str(data.get("summary") or base.summary)[:300],
                "llm",
            )
        except (HTTPError, TimeoutError, ValueError, KeyError) as e:
            self.failures += 1
            log.info("LLM summary failed, fallback to rule: %s", e)
            return base

    async def _call(self, content: str) -> str:
        if self.provider == "anthropic":
            r = await self.client.post(
                f"{self.base}/v1/messages",
                json_body={
                    "model": self.model,
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": PROMPT + content}],
                },
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            )
            if r.status != 200:
                raise HTTPError("http", f"LLM HTTP {r.status}")
            return "".join(b.get("text", "") for b in r.json().get("content", []))
        r = await self.client.post(
            f"{self.base}/v1/chat/completions",
            json_body={
                "model": self.model,
                "messages": [{"role": "user", "content": PROMPT + content}],
                "max_tokens": 300,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        if r.status != 200:
            raise HTTPError("http", f"LLM HTTP {r.status}")
        return r.json()["choices"][0]["message"]["content"]
