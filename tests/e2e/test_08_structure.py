"""Structure lifecycle: create -> write -> activate -> read -> delete."""

import pytest
import pytest_asyncio

from .helpers import call_tool_ok, safe_delete


@pytest.mark.asyncio
class TestStructureLifecycle:
    """Full CRUD lifecycle for a dictionary structure."""

    _failed: bool = False
    _struc_name: str = ""

    @pytest.fixture(autouse=True, scope="class")
    def setup_names(self, run_id):
        TestStructureLifecycle._struc_name = f"ZE2E_STRC_{run_id}"
        TestStructureLifecycle._failed = False

    @pytest_asyncio.fixture(autouse=True, scope="class")
    async def cleanup(self, mcp_client, system_name, run_id):
        yield
        name = f"ZE2E_STRC_{run_id}"
        await safe_delete(mcp_client, "abap_structure_delete", {
            "name": [name],
            "system": system_name,
        })

    @pytest.fixture(autouse=True)
    def skip_if_prior_failed(self):
        if self.__class__._failed:
            pytest.skip("prior lifecycle step failed")

    async def test_01_create(self, mcp_client, system_name, package_name):
        """Create the structure."""
        try:
            await call_tool_ok(mcp_client, "abap_structure_create", {
                "name": self._struc_name,
                "description": "E2E test structure",
                "package": package_name,
                "system": system_name,
            })
        except Exception:
            self.__class__._failed = True
            raise

    async def test_02_write(self, mcp_client, system_name):
        """Write structure definition."""
        source = (
            f"@EndUserText.label : 'E2E test structure'\n"
            "@AbapCatalog.enhancement.category : #NOT_EXTENSIBLE\n"
            f"define structure {self._struc_name.lower()} {{\n"
            "  id   : sysuuid_x16;\n"
            "  name : char30;\n"
            "}\n"
        )
        try:
            await call_tool_ok(mcp_client, "abap_structure_write", {
                "name": self._struc_name,
                "source_data": source,
                "system": system_name,
            })
        except Exception:
            self.__class__._failed = True
            raise

    async def test_03_activate(self, mcp_client, system_name):
        """Activate the structure."""
        try:
            await call_tool_ok(mcp_client, "abap_structure_activate", {
                "name": [self._struc_name],
                "system": system_name,
            })
        except Exception:
            self.__class__._failed = True
            raise

    async def test_04_read(self, mcp_client, system_name):
        """Read back structure definition and verify."""
        try:
            content = await call_tool_ok(mcp_client, "abap_structure_read", {
                "name": self._struc_name,
                "system": system_name,
            })
            assert "name" in content.lower()
        except Exception:
            self.__class__._failed = True
            raise

    async def test_05_delete(self, mcp_client, system_name):
        """Delete the structure."""
        await call_tool_ok(mcp_client, "abap_structure_delete", {
            "name": [self._struc_name],
            "system": system_name,
        })
