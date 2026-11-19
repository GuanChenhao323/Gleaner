"""Pure validation and comparison for IC-READING-SOURCE-001."""

from __future__ import annotations

import copy
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .monitors import ContractError, assignment_content, compact, string, web_url
from .resident_contract import ResidentContract
from .source_identity import account_probe
from .web_captures import normalized_query

FAILURES = {
    "need_login",
    "account_unknown",
    "account_mismatch",
    "route_mismatch",
    "view_mismatch",
    "permission_denied",
    "render_timeout",
    "selection_missing",
    "no_match",
    "unsupported",
    "failed",
    "worker_interrupted",
    "preview_only",
    "private_source_required",
    "tab_missing",
    "tab_rebind_required",
    "tab_ambiguous",
    "waiting_page",
    "protocol_unavailable",
    "user_busy",
    "single_account_conflict",
}
INTERVALS = {1800, 3600, 7200}


class ReadingRecipe:
    """A query recipe is not a provisional DOM selector or an exported session."""

    def validate(self, value: Any) -> dict[str, Any]:
        keys = {
            "version",
            "url",
            "query",
            "match_scope",
            "intent",
            "choice",
            "source",
            "binding",
            "view",
        }
        if (
            not isinstance(value, dict)
            or set(value) - (keys | {"source_label", "representation", "account_probe", "resident"})
            or not keys <= set(value)
            or type(value["version"]) is not int
            or value["version"] != 1
        ):
            raise ContractError("invalid_reading_recipe")
        recipe = copy.deepcopy(value)
        recipe["source_label"] = string(value.get("source_label", ""), 80, empty=True)
        url, query = web_url(value["url"]), string(value["query"], 200)
        if any(
            any(
                w in k.lower()
                for w in ("token", "ticket", "session", "password", "secret", "authorization")
            )
            for k, _ in parse_qsl(urlsplit(url).query)
        ):
            raise ContractError("invalid_url")
        if value["source"] not in ("generic", "moodle", "student", "fie") or value[
            "match_scope"
        ] not in ("content", "title"):
            raise ContractError("invalid_reading_recipe")
        intent = value["intent"]
        if (
            not isinstance(intent, dict)
            or intent.get("version") != 2
            or intent.get("query") != query
            or not isinstance(intent.get("fields"), list)
            or len(compact(intent)) > 2000
        ):
            raise ContractError("invalid_reading_recipe")
        allowed = {
            "version",
            "query",
            "mode",
            "match_scope",
            "kind",
            "target",
            "keyword",
            "fields",
            "current",
            "all",
        }
        if set(intent) - allowed or any(not isinstance(f, str) for f in intent["fields"]):
            raise ContractError("invalid_reading_recipe")
        string(value["choice"], 100, empty=True)
        view = value["view"]
        if (
            not isinstance(view, dict)
            or len(compact(view)) > 2000
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in view.items())
        ):
            raise ContractError("invalid_view")
        binding = value["binding"]
        if (
            not isinstance(binding, dict)
            or set(binding) != {"adapter", "origin", "account_key"}
            or binding["adapter"] != value["source"]
        ):
            raise ContractError("invalid_binding")
        origin = web_url(binding["origin"])
        if (urlsplit(origin).scheme, urlsplit(origin).netloc) != (
            urlsplit(url).scheme,
            urlsplit(url).netloc,
        ):
            raise ContractError("cross_origin_target")
        string(binding["account_key"], 200)
        if "account_probe" in value:
            if value["source"] != "generic" or binding["account_key"] in ("public", "unverified"):
                raise ContractError("invalid_account_proof")
            account_probe(value["account_probe"], binding["account_key"])
        elif value["source"] == "generic" and binding["account_key"] not in (
            "public",
            "unverified",
        ):
            raise ContractError("invalid_account_proof")
        if value["source"] in ("moodle", "student") and binding["account_key"] in (
            "public",
            "unverified",
        ):
            raise ContractError("account_required")
        if "representation" in value and (
            value["representation"] != "timeline_summary"
            or value["source"] != "moodle"
            or intent.get("target", "").casefold() not in ("timeline", "时间线")
            or intent.get("kind") != "auto"
            or intent["fields"]
            or value["choice"]
            or value["view"]
            or value["match_scope"] != "content"
        ):
            raise ContractError("invalid_reading_recipe")
        if "resident" in value:
            recipe["resident"] = ResidentContract().validate(value["resident"])
        recipe.update(url=url, query=query)
        return recipe

    def identity(self, recipe: dict[str, Any]) -> list[Any]:
        values = [
            recipe["binding"],
            recipe.get("source_label", ""),
            recipe["url"],
            normalized_query(recipe["query"]),
            recipe["match_scope"],
            recipe["choice"],
            recipe["view"],
        ]
        if "representation" in recipe:
            values.append(recipe["representation"])
        return values


def semantic_snapshot(snapshot: dict[str, Any], generic: bool) -> list[Any]:
    """Ignore positions/evidence churn, keep duplicate fragments and actual fields."""
    if generic:
        values = [
            [f["title"], f["text"], f["url"], f["fields"]]
            if snapshot.get("collection_type") == "timeline_summary"
            else [f["title"], f["text"]]
            for f in snapshot["fragments"]
        ]
    else:
        values = [[t["entity_id"], t["locator"], assignment_content(t["raw"])] for t in snapshot["targets"]]
    return sorted(values, key=compact)
