"""Helper utilities for E2E tests."""

import json
import logging
from typing import Any

from fastmcp import Client

logger = logging.getLogger("e2e")


def _extract_text(result) -> str:
    """Extract text content from a CallToolResult."""
    if not result.content:
        return ""
    first = result.content[0]
    if hasattr(first, "text"):
        return first.text
    return str(first)


def _parse_sapcli_result(text: str) -> tuple[bool, list[str], str]:
    """Parse the sapcli tool result format: {"result": [success, log_msgs, contents]}.

    Returns (success, log_messages, contents).
    Falls back to (True, [], text) if format doesn't match.
    """
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "result" in parsed:
            success, log_msgs, contents = parsed["result"]
            return (bool(success), list(log_msgs), str(contents))
        if isinstance(parsed, list) and len(parsed) == 3:
            success, log_msgs, contents = parsed
            return (bool(success), list(log_msgs), str(contents))
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return (True, [], text)


async def call_tool_ok(client: Client, tool_name: str, args: dict[str, Any]) -> str:
    """Call a tool and assert it succeeds. Returns the content text."""
    result = await client.call_tool(tool_name, args, raise_on_error=False)
    text = _extract_text(result)

    if result.is_error:
        raise AssertionError(f"Tool {tool_name} returned error: {text}")

    success, log_msgs, contents = _parse_sapcli_result(text)
    assert success, f"Tool {tool_name} failed: {log_msgs}"
    return contents


async def call_tool_check(
    client: Client, tool_name: str, args: dict[str, Any]
) -> tuple[bool, list[str], str]:
    """Call a tool and return (success, log_messages, contents) without asserting."""
    result = await client.call_tool(tool_name, args, raise_on_error=False)
    text = _extract_text(result)

    if result.is_error:
        return (False, [text], "")

    return _parse_sapcli_result(text)


async def safe_delete(
    client: Client, tool_name: str, args: dict[str, Any]
) -> None:
    """Attempt to delete an object; log but don't fail on errors."""
    try:
        await client.call_tool(tool_name, args, raise_on_error=False)
        logger.info("Deleted via %s: %s", tool_name, args.get("name", args))
    except Exception as exc:
        logger.warning(
            "Delete via %s failed (non-fatal): %s — %s",
            tool_name, args.get("name"), exc
        )
