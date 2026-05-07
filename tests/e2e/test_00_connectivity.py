"""Smoke test: verify connectivity to the SAP system."""

import pytest

from .helpers import call_tool_ok, call_tool_check


@pytest.mark.asyncio
class TestConnectivity:
    """Verify basic connectivity to the SAP sandbox."""

    async def test_01_system_info(self, mcp_client, system_name):
        """Verify system is reachable via abap_abap_systeminfo."""
        content = await call_tool_ok(
            mcp_client, "abap_abap_systeminfo", {"system": system_name}
        )
        assert content  # Non-empty response means connected

    async def test_02_package_list_tmp(self, mcp_client, system_name):
        """Verify $TMP is listable (basic ADT connectivity check)."""
        content = await call_tool_ok(
            mcp_client, "abap_package_list", {
                "name": "$TMP",
                "system": system_name,
            }
        )
        # $TMP always exists — content may be empty but call must succeed
        assert content is not None

    async def test_03_gcts_repolist(self, mcp_client, system_name):
        """Verify gCTS connectivity (different conn_type than ADT)."""
        success, log_msgs, content = await call_tool_check(
            mcp_client, "abap_gcts_repolist", {"system": system_name}
        )
        if not success:
            pytest.skip(f"gCTS not available on this system: {log_msgs}")
        # gCTS repolist returns repo data (may be empty list on fresh system)
        assert content is not None
