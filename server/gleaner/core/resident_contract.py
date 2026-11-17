"""Opaque browser references. They identify an agreed context, not an OAuth account."""

from __future__ import annotations

import copy
import uuid
from typing import Any
from urllib.parse import urlsplit

from .monitors import ContractError

INTERVALS = {1800, 3600, 7200}


class ResidentContract:
    def validate(self, value: Any) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "session_id", "page_id", "refresh", "interval_s"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["refresh"] != "reload"
            or type(value["interval_s"]) is not int
            or value["interval_s"] not in INTERVALS
        ):
            raise ContractError("invalid_resident")
        for key in ("session_id", "page_id"):
            try:
                if str(uuid.UUID(value[key])) != value[key] or uuid.UUID(value[key]).version != 4:
                    raise ValueError
            except (ValueError, TypeError, AttributeError) as e:
                raise ContractError("invalid_resident") from e
        return dict(value)

    @staticmethod
    def group(recipe: dict[str, Any]) -> str | None:
        return recipe.get("resident", {}).get("page_id")

    @staticmethod
    def at_interval(recipe: dict[str, Any], interval: int) -> dict[str, Any]:
        value = copy.deepcopy(recipe)
        if "resident" in value:
            value["resident"]["interval_s"] = interval
        return value

    @staticmethod
    def page_view(recipe: dict[str, Any]) -> dict[str, str]:
        # Field projection changes the output, not the physical page to refresh.
        return {k: v for k, v in recipe["view"].items() if k != "projection"}

    @staticmethod
    def origin(recipe: dict[str, Any]) -> str:
        url = urlsplit(recipe["url"])
        return f"{url.scheme}://{url.netloc}"
