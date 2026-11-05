"""Shared agent tool contracts and bounded execution primitives. No application startup."""
import json
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class AgentToolRequest:
    tool_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False


def normalize_tool_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in plan.get("tool_calls") or []:
        if not isinstance(item, dict):
            continue
        tool_key = str(item.get("tool_key") or "").strip()
        if not tool_key:
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        payload_json = item.get("payload_json")
        if not payload and isinstance(payload_json, str) and payload_json.strip():
            try:
                parsed_payload = json.loads(payload_json)
                payload = parsed_payload if isinstance(parsed_payload, dict) else {}
            except json.JSONDecodeError:
                payload = {}
        normalized.append(
            {
                "tool_key": tool_key,
                "payload": payload,
                "rationale": str(item.get("rationale") or "").strip(),
            }
        )
    return normalized[:5]


def bounded_iterations(requested: int) -> int:
    return max(1, min(requested, 4))


def validate_local_plan(steps, allowed_agents, *, max_steps=3):
    """Validate a coordinator's bounded serial delegation before any execution."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= min(max_steps, 4):
        raise ValueError("The coordinator must select a bounded list of steps.")
    for step in steps:
        if set(step) != {"agent", "instruction"} or step["agent"] not in allowed_agents:
            raise ValueError("The coordinator requested an unavailable agent.")
        if not isinstance(step["instruction"], str) or not 1 <= len(step["instruction"].strip()) <= 2000:
            raise ValueError("Invalid agent instruction.")
    return steps
