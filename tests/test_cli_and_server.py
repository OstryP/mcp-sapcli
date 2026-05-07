"""Tests for sapclimcp.server and sapclimcp.cli."""

import asyncio
import os
from unittest.mock import patch, MagicMock

import pytest

from sapclimcp.server import create_mcp_server, VERIFIED_COMMANDS
from sapclimcp.cli import parse_args, main
from sapclimcp.config import ConfigError


class TestParseArgs:
    """Tests for CLI argument parsing."""

    def test_defaults(self):
        args = parse_args([])
        assert args.experimental is False
        assert args.config is None
        assert args.stdio is False
        assert args.host == "127.0.0.1"
        assert args.port == 8000

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

    @patch('sapclimcp.cli.create_mcp_server')
    def test_main_stdio(self, mock_create, monkeypatch):
        monkeypatch.delenv('SAPCLI_MCP_CONFIG', raising=False)
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        main(["--stdio"])

        mock_create.assert_called_once_with(
            experimental=False,
            config_path=None,
        )
        mock_server.run.assert_called_once_with(transport="stdio")

    @patch('sapclimcp.cli.create_mcp_server')
    def test_main_http(self, mock_create, monkeypatch):
        monkeypatch.delenv('SAPCLI_MCP_CONFIG', raising=False)
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        main(["--host", "0.0.0.0", "--port", "9000"])

        mock_create.assert_called_once_with(
            experimental=False,
            config_path=None,
        )
        mock_server.run.assert_called_once_with(
            transport="http", host="0.0.0.0", port=9000
        )

    @patch('sapclimcp.cli.create_mcp_server')
    def test_main_experimental_with_config(self, mock_create):
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        main(["--experimental", "--config", "my.json", "--stdio"])

        mock_create.assert_called_once_with(
            experimental=True,
            config_path="my.json",
        )

    @patch('sapclimcp.cli.create_mcp_server')
    def test_main_config_from_env(self, mock_create, monkeypatch):
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        monkeypatch.setenv('SAPCLI_MCP_CONFIG', '/env/config.json')
        main(["--stdio"])

        mock_create.assert_called_once_with(
            experimental=False,
            config_path="/env/config.json",
        )

    @patch('sapclimcp.cli.create_mcp_server')
    def test_cli_arg_takes_precedence_over_env(self, mock_create, monkeypatch):
        """CLI --config flag takes priority over SAPCLI_MCP_CONFIG env var."""
        mock_server = MagicMock()
        mock_create.return_value = mock_server

        monkeypatch.setenv('SAPCLI_MCP_CONFIG', '/env/config.json')
        main(["--stdio", "--config", "explicit.json"])

        mock_create.assert_called_once_with(
            experimental=False,
            config_path="explicit.json",
        )

    @patch('sapclimcp.cli.create_mcp_server')
    def test_main_exits_on_config_error(self, mock_create):
        mock_create.side_effect = ConfigError("bad config")

        with pytest.raises(SystemExit) as exc_info:
            main(["--stdio", "--config", "bad.json"])

        assert "Configuration error" in str(exc_info.value)
