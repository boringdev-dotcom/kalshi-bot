"""Versioned playbook snapshots. Hard caps live in limits and are never versioned as proposals."""

from __future__ import annotations

import json
from typing import Any, Optional

from kalshi_bot.playbook import PLAYBOOK_NOTES, default_rules
from kalshi_bot.store import Store

HARD_CAP_KEYS = frozenset(
    {
        "max_contracts_per_match",
        "max_contracts_per_day",
        "max_daily_loss_cents",
        "max_contracts_per_match_hard",
        "MAX_CONTRACTS_PER_MATCH",
        "MAX_CONTRACTS_PER_DAY",
        "MAX_CONTRACTS_PER_MATCH_HARD",
    }
)


def default_playbook_body() -> dict[str, Any]:
    return {k: v for k, v in default_rules().items() if k not in HARD_CAP_KEYS}


def ensure_playbook_v1(store: Store) -> dict[str, Any]:
    existing = store.latest_playbook_version()
    if existing:
        return existing
    body = default_playbook_body()
    store.add_playbook_version(
        {
            "version": 1,
            "notes": PLAYBOOK_NOTES.get("source") or "seeded playbook",
            "body": body,
            "parent_version": None,
        }
    )
    store.set_control("playbook_version", "1")
    return store.latest_playbook_version() or {"version": 1, "body": body}


def current_version_number(store: Store) -> int:
    raw = store.get_control("playbook_version")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    latest = store.latest_playbook_version()
    return int(latest["version"]) if latest else 1


def active_rules(store: Optional[Store] = None) -> dict[str, Any]:
    if store is None:
        return default_playbook_body()
    ensure_playbook_v1(store)
    raw = store.get_control("playbook_version")
    version = None
    if raw:
        try:
            version = store.get_playbook_version(int(raw))
        except ValueError:
            version = None
    if version is None:
        version = store.latest_playbook_version()
    body = (version or {}).get("body") or default_playbook_body()
    return dict(body)


def merge_diff(base: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in diff.items():
        if key in HARD_CAP_KEYS:
            continue
        out[key] = value
    return out


def publish_version(
    store: Store,
    *,
    diff: dict[str, Any],
    notes: str,
    parent: Optional[int] = None,
) -> dict[str, Any]:
    ensure_playbook_v1(store)
    current = store.latest_playbook_version() or {"version": 1, "body": default_playbook_body()}
    parent = parent if parent is not None else int(current["version"])
    body = merge_diff(current.get("body") or default_playbook_body(), diff)
    nxt = int(current["version"]) + 1
    store.add_playbook_version(
        {
            "version": nxt,
            "notes": notes,
            "body": body,
            "parent_version": parent,
        }
    )
    store.set_control("playbook_version", str(nxt))
    return store.get_playbook_version(nxt) or {"version": nxt, "body": body}


def version_payload(store: Store) -> dict[str, Any]:
    ensure_playbook_v1(store)
    current = store.latest_playbook_version()
    return {
        "current": current_version_number(store),
        "versions": store.list_playbook_versions(),
        "rules": active_rules(store),
        "body_json": json.dumps((current or {}).get("body") or {}),
    }
