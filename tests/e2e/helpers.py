"""Helper utilities for E2E tests."""

import json
import logging
from typing import Any

from fastmcp import Client

logger = logging.getLogger("e2e")


def _parse_result(result) -> tuple[bool, list[str], str]:
    """Parse a CallToolResult into (success, log_messages, contents).

    The sapcli MCP tools return structured_content: {"result": [success, log_msgs, contents]}.
    Falls back to content[0].text if structured_content is unavailable.
    """
    # Prefer structured_content — always present for sapcli tools
    if result.structured_content and "result" in result.structured_content:
        success, log_msgs, contents = result.structured_content["result"]
        return (bool(success), list(log_msgs), str(contents))

    # Fallback: text content
    text = ""
    if result.content and hasattr(result.content[0], "text") and result.content[0].text:
        text = result.content[0].text

    # Try parsing as JSON (older format)
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

    if result.is_error:
        text = ""
        if result.content and hasattr(result.content[0], "text"):
            text = result.content[0].text or ""
        raise AssertionError(f"Tool {tool_name} returned error: {text}")

    success, log_msgs, contents = _parse_result(result)
    assert success, f"Tool {tool_name} failed: {log_msgs}"
    return contents


async def call_tool_check(
    client: Client, tool_name: str, args: dict[str, Any]
) -> tuple[bool, list[str], str]:
    """Call a tool and return (success, log_messages, contents) without asserting."""
    result = await client.call_tool(tool_name, args, raise_on_error=False)

    if result.is_error:
        text = ""
        if result.content and hasattr(result.content[0], "text"):
            text = result.content[0].text or ""
        return (False, [text], "")

    return _parse_result(result)


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
