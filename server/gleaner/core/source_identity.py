"""Validate browser account proof descriptors, separately from webpage contents.

The server trusts the authenticated extension to observe DOM, not source labels.
This descriptor is not an OAuth assertion or evidence of real-site compatibility.
"""

from __future__ import annotations

import re
from typing import Any

from .monitors import ContractError, string

PROBE = "account-control-email-v1"


def account_identity(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "probe", "account_key", "display"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["probe"] != PROBE
        or not isinstance(value["account_key"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["account_key"])
    ):
        raise ContractError("invalid_account_proof")
    display = string(value["display"], 100)
    if not re.fullmatch(r"[^@\s]+\*\*\*@[^@\s]+", display):
        raise ContractError("invalid_account_proof")
    return {**value, "display": display}


def account_probe(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"version", "kind", "display"}:
        raise ContractError("invalid_account_proof")
    account_identity(
        {
            "version": value["version"],
            "probe": value["kind"],
            "display": value["display"],
            "account_key": key,
        }
    )
    return value
