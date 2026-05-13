"""Tests for sapclimcp.server and sapclimcp.cli."""

import asyncio
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from sapclimcp.cli import main, parse_args
from sapclimcp.config import KEYRING_SERVICE
from sapclimcp.errors import ConfigError
from sapclimcp.server import VERIFIED_COMMANDS, create_mcp_server


class TestParseArgs:
    """Tests for CLI argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert args.experimental is False
        assert args.config is None
        assert args.stdio is False
        assert args.host == "127.0.0.1"
        assert args.port == 8000
        assert args.log_level is None

    def test_log_level_valid(self):
        args = parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_log_level_case_insensitive(self):
        args = parse_args(["--log-level", "debug"])
        assert args.log_level == "DEBUG"

    def test_log_level_invalid(self):
        with pytest.raises(SystemExit):
            parse_args(["--log-level", "VERBOSE"])

    def test_experimental(self):
        args = parse_args(["--experimental"])
        assert args.experimental is True

    def test_stdio(self):
        args = parse_args(["--stdio"])
        assert args.stdio is True

    def test_config(self):
        args = parse_args(["--config", "/path/to/config.json"])
        assert args.config == "/path/to/config.json"

    def test_host_and_port(self):
        args = parse_args(["--host", "0.0.0.0", "--port", "9000"])
        assert args.host == "0.0.0.0"
        assert args.port == 9000


class TestCreateMcpServer:
    """Tests for create_mcp_server."""

    def test_creates_server_with_verified_tools(self):
        server = create_mcp_server()
        assert server.name == "sapcli"
        # Verify tools were actually registered (not an empty server)
        tools = asyncio.run(server.list_tools())
        assert len(tools) >= len(VERIFIED_COMMANDS)

    def test_creates_server_with_name(self):
        server = create_mcp_server(name="test-server")
        assert server.name == "test-server"

    def test_raises_config_error_on_bad_config(self, tmp_path):
        bad_config = tmp_path / "bad.json"
        bad_config.write_text("not json")
        with pytest.raises(ConfigError):
            create_mcp_server(config_path=str(bad_config))

    def test_raises_config_error_on_missing_config(self):
        with pytest.raises(ConfigError):
            create_mcp_server(config_path="/nonexistent/path.json")


class TestCliMain:
    """Tests for cli.main()."""

    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_stdio(self, mock_create, monkeypatch):
        monkeypatch.delenv("SAPCLI_MCP_CONFIG", raising=False)
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        main(["--stdio"])

        mock_create.assert_called_once_with(
            experimental=False,
            config_path=None,
        )
        mock_server.run.assert_called_once_with(transport="stdio")

    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_http(self, mock_create, monkeypatch):
        monkeypatch.delenv("SAPCLI_MCP_CONFIG", raising=False)
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        main(["--host", "0.0.0.0", "--port", "9000"])

        mock_create.assert_called_once_with(
            experimental=False,
            config_path=None,
        )
        mock_server.run.assert_called_once_with(transport="http", host="0.0.0.0", port=9000)

    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_experimental_with_config(self, mock_create):
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        main(["--experimental", "--config", "my.json", "--stdio"])

        mock_create.assert_called_once_with(
            experimental=True,
            config_path="my.json",
        )

    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_config_from_env(self, mock_create, monkeypatch):
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        monkeypatch.setenv("SAPCLI_MCP_CONFIG", "/env/config.json")
        main(["--stdio"])

        mock_create.assert_called_once_with(
            experimental=False,
            config_path="/env/config.json",
        )

    @patch("sapclimcp.cli.create_mcp_server")
    def test_cli_arg_takes_precedence_over_env(self, mock_create, monkeypatch):
        """CLI --config flag takes priority over SAPCLI_MCP_CONFIG env var."""
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        monkeypatch.setenv("SAPCLI_MCP_CONFIG", "/env/config.json")
        main(["--stdio", "--config", "explicit.json"])

        mock_create.assert_called_once_with(
            experimental=False,
            config_path="explicit.json",
        )

    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_exits_on_config_error(self, mock_create):
        mock_create.side_effect = ConfigError("bad config")

        with pytest.raises(SystemExit) as exc_info:
            main(["--stdio", "--config", "bad.json"])

        msg = str(exc_info.value)
        assert "configuration error" in msg
        assert "bad config" in msg

    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_exits_on_unexpected_error(self, mock_create):
        """Unexpected exceptions produce actionable error instead of traceback."""
        mock_create.side_effect = RuntimeError("something broke")

        with pytest.raises(SystemExit) as exc_info:
            main(["--stdio"])

        msg = str(exc_info.value)
        assert "unexpected error" in msg
        assert "RuntimeError" in msg
        assert "something broke" in msg

    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_exits_on_import_error(self, mock_create):
        """Generic ImportError produces guidance about installing dependencies."""
        mock_create.side_effect = ImportError("No module named 'foo'", name="foo")

        with pytest.raises(SystemExit) as exc_info:
            main(["--stdio"])

        msg = str(exc_info.value)
        assert "missing dependency" in msg
        assert "sapcli is not installed" not in msg

    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_exits_on_sapcli_import_error(self, mock_create):
        """ImportError for sap.* produces sapcli-specific install guidance."""
        mock_create.side_effect = ImportError("No module named 'sap'", name="sap")

        with pytest.raises(SystemExit) as exc_info:
            main(["--stdio"])

        msg = str(exc_info.value)
        assert "sapcli is not installed" in msg
        assert "uv pip install" in msg

    @patch("sapclimcp.cli.logging.basicConfig")
    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_log_level_calls_basicConfig(self, mock_create, mock_basic, monkeypatch):
        monkeypatch.delenv("SAPCLI_MCP_CONFIG", raising=False)
        monkeypatch.delenv("SAPCLI_MCP_LOG_LEVEL", raising=False)
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        import logging

        main(["--stdio", "--log-level", "DEBUG"])

        mock_basic.assert_called_once()
        kwargs = mock_basic.call_args.kwargs
        assert kwargs["level"] == logging.DEBUG
        assert kwargs["stream"] is sys.stderr
        assert kwargs["force"] is True

    @patch("sapclimcp.cli.logging.basicConfig")
    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_no_log_level_skips_basicConfig(self, mock_create, mock_basic, monkeypatch):
        monkeypatch.delenv("SAPCLI_MCP_CONFIG", raising=False)
        monkeypatch.delenv("SAPCLI_MCP_LOG_LEVEL", raising=False)
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        main(["--stdio"])

        mock_basic.assert_not_called()

    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_stdio_debug_logs_warning(self, mock_create, monkeypatch, capsys):
        monkeypatch.delenv("SAPCLI_MCP_CONFIG", raising=False)
        monkeypatch.delenv("SAPCLI_MCP_LOG_LEVEL", raising=False)
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        main(["--stdio", "--log-level", "DEBUG"])

        captured = capsys.readouterr()
        assert "stdio" in captured.err

    @patch("sapclimcp.cli.logging.basicConfig")
    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_log_level_from_env(self, mock_create, mock_basic, monkeypatch):
        monkeypatch.delenv("SAPCLI_MCP_CONFIG", raising=False)
        monkeypatch.setenv("SAPCLI_MCP_LOG_LEVEL", "warning")
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        import logging

        main(["--stdio"])

        mock_basic.assert_called_once()
        kwargs = mock_basic.call_args.kwargs
        assert kwargs["level"] == logging.WARNING
        assert kwargs["stream"] is sys.stderr
        assert kwargs["force"] is True

    @patch("sapclimcp.cli.logging.basicConfig")
    @patch("sapclimcp.cli.create_mcp_server")
    def test_main_log_level_invalid_env_skips(self, mock_create, mock_basic, monkeypatch):
        monkeypatch.delenv("SAPCLI_MCP_CONFIG", raising=False)
        monkeypatch.setenv("SAPCLI_MCP_LOG_LEVEL", "VERBOSE")
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        main(["--stdio"])

        mock_basic.assert_not_called()


# ---------------------------------------------------------------------------
# Credential CLI subcommand
# ---------------------------------------------------------------------------


class TestCliCredential:
    """Tests for sapcli-mcp credential set/get/delete."""

    def test_parse_credential_set(self):
        args = parse_args(["credential", "set", "MY_KEY", "my_value"])
        assert args.command == "credential"
        assert args.cred_action == "set"
        assert args.key == "MY_KEY"
        assert args.value == "my_value"

    def test_parse_credential_set_no_value(self):
        args = parse_args(["credential", "set", "MY_KEY"])
        assert args.value is None

    def test_parse_credential_get(self):
        args = parse_args(["credential", "get", "MY_KEY"])
        assert args.command == "credential"
        assert args.cred_action == "get"
        assert args.key == "MY_KEY"

    def test_parse_credential_delete(self):
        args = parse_args(["credential", "delete", "MY_KEY"])
        assert args.command == "credential"
        assert args.cred_action == "delete"
        assert args.key == "MY_KEY"

    @patch("sapclimcp.cli.keyring")
    def test_credential_set(self, mock_keyring, capsys):
        main(["credential", "set", "TEST_KEY", "test_value"])
        mock_keyring.set_password.assert_called_once_with(KEYRING_SERVICE, "TEST_KEY", "test_value")
        assert "Stored credential: TEST_KEY" in capsys.readouterr().out

    @patch("sapclimcp.cli.keyring")
    def test_credential_set_from_stdin(self, mock_keyring, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO("stdin_value\n"))
        main(["credential", "set", "TEST_KEY"])
        mock_keyring.set_password.assert_called_once_with(
            KEYRING_SERVICE, "TEST_KEY", "stdin_value"
        )

    @patch("sapclimcp.cli.keyring")
    def test_credential_set_empty_exits(self, mock_keyring, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO(""))
        with pytest.raises(SystemExit) as exc_info:
            main(["credential", "set", "TEST_KEY"])
        assert exc_info.value.code == 1
        mock_keyring.set_password.assert_not_called()

    @patch("sapclimcp.cli.keyring")
    def test_credential_get_found(self, mock_keyring, capsys):
        mock_keyring.get_password.return_value = "found_value"
        main(["credential", "get", "TEST_KEY"])
        mock_keyring.get_password.assert_called_once_with(KEYRING_SERVICE, "TEST_KEY")
        assert "found_value" in capsys.readouterr().out

    @patch("sapclimcp.cli.keyring")
    def test_credential_get_missing_exits(self, mock_keyring):
        mock_keyring.get_password.return_value = None
        with pytest.raises(SystemExit) as exc_info:
            main(["credential", "get", "MISSING_KEY"])
        assert exc_info.value.code == 1

    @patch("sapclimcp.cli.keyring")
    def test_credential_delete_found(self, mock_keyring, capsys):
        main(["credential", "delete", "TEST_KEY"])
        mock_keyring.delete_password.assert_called_once_with(KEYRING_SERVICE, "TEST_KEY")
        assert "Deleted credential: TEST_KEY" in capsys.readouterr().out

    @patch("sapclimcp.cli.keyring")
    def test_credential_delete_missing_exits(self, mock_keyring):
        import keyring.errors as kr_errors

        mock_keyring.errors = kr_errors
        mock_keyring.delete_password.side_effect = kr_errors.PasswordDeleteError("not found")
        with pytest.raises(SystemExit) as exc_info:
            main(["credential", "delete", "MISSING_KEY"])
        assert exc_info.value.code == 1

    def test_credential_no_action_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["credential"])
        assert exc_info.value.code == 1
