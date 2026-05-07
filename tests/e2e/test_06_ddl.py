"""CDS view (DDL) lifecycle: create -> write -> activate -> read -> delete."""

import pytest
import pytest_asyncio

from .helpers import call_tool_ok, safe_delete


@pytest.mark.asyncio
class TestDDLLifecycle:
    """Full CRUD lifecycle for a CDS view (DDL source)."""

    _failed: bool = False
    _ddl_name: str = ""

    @pytest.fixture(autouse=True, scope="class")
    def setup_names(self, run_id):
        TestDDLLifecycle._ddl_name = f"ZE2E_DDL_{run_id}"
        TestDDLLifecycle._failed = False

    @pytest_asyncio.fixture(autouse=True, scope="class")
    async def cleanup(self, mcp_client, system_name, run_id):
        yield
        name = f"ZE2E_DDL_{run_id}"
        await safe_delete(mcp_client, "abap_ddl_delete", {
            "name": [name],
            "system": system_name,
        })

    @pytest.fixture(autouse=True)
    def skip_if_prior_failed(self):
        if self.__class__._failed:
            pytest.skip("prior lifecycle step failed")

    async def test_01_create(self, mcp_client, system_name, package_name):
        """Create the CDS view."""
        try:
            await call_tool_ok(mcp_client, "abap_ddl_create", {
                "name": self._ddl_name,
                "description": "E2E test CDS view",
                "package": package_name,
                "system": system_name,
            })
        except Exception:
            self.__class__._failed = True
            raise

    async def test_02_write(self, mcp_client, system_name):
        """Write CDS view source."""
        source = (
            f"@AbapCatalog.sqlViewName: '{self._ddl_name[:16]}V'\n"
            "@AbapCatalog.compiler.compareFilter: true\n"
            "@AccessControl.authorizationCheck: #NOT_REQUIRED\n"
            f"@EndUserText.label: 'E2E test view'\n"
            f"define view {self._ddl_name} as select from t000 {{\n"
            "  key mandt\n"
            "}}\n"
        )
        try:
            await call_tool_ok(mcp_client, "abap_ddl_write", {
                "name": self._ddl_name,
                "source_data": source,
                "system": system_name,
            })
        except Exception:
            self.__class__._failed = True
            raise

    async def test_03_activate(self, mcp_client, system_name):
        """Activate the CDS view."""
        try:
            await call_tool_ok(mcp_client, "abap_ddl_activate", {
                "name": [self._ddl_name],
                "system": system_name,
            })
        except Exception:
            self.__class__._failed = True
            raise

    async def test_04_read(self, mcp_client, system_name):
        """Read back CDS source and verify."""
        try:
            content = await call_tool_ok(mcp_client, "abap_ddl_read", {
                "name": self._ddl_name,
                "system": system_name,
            })
            assert "t000" in content.lower()
        except Exception:
            self.__class__._failed = True
            raise

    async def test_05_delete(self, mcp_client, system_name):
        """Delete the CDS view."""
        await call_tool_ok(mcp_client, "abap_ddl_delete", {
            "name": [self._ddl_name],
            "system": system_name,
        })
