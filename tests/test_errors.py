"""Unit tests for sapclimcp.errors module."""

import pytest

from sapclimcp.errors import (
    format_auth_error,
    format_connection_error,
    format_command_error,
    format_startup_error,
)


class TestFormatAuthError:
    """Tests for format_auth_error."""

    def test_cookie_auth_mentions_sso_cookie(self):
        err = Exception("HTTP 401")
        msg = format_auth_error(
            auth_type='cookie',
            system_name='DEV',
            host='dev.sap.example.com',
            original_error=err,
        )
        assert "SSO cookie" in msg
        assert "DEV" in msg
        assert "dev.sap.example.com" in msg

    def test_cookie_auth_after_retry(self):
        err = Exception("HTTP 401")
        msg = format_auth_error(
            auth_type='cookie',
            system_name='DEV',
            host='dev.sap.example.com',
            original_error=err,
            is_retry=True,
        )
        assert "after retry" in msg
        assert "SSO cookie" in msg
        assert "$ENV_VAR" in msg

    def test_basic_auth_mentions_user_password(self):
        err = Exception("HTTP 401")
        msg = format_auth_error(
            auth_type='basic',
            system_name='QAS',
            host='qas.sap.example.com',
            original_error=err,
        )
        assert "user" in msg
        assert "password" in msg
        assert "QAS" in msg
        assert "qas.sap.example.com" in msg

    def test_basic_auth_mentions_account_locked(self):
        err = Exception("HTTP 401")
        msg = format_auth_error(
            auth_type='basic',
            system_name='QAS',
            host='qas.sap.example.com',
            original_error=err,
        )
        assert "locked" in msg

    def test_basic_auth_after_retry(self):
        err = Exception("HTTP 401")
        msg = format_auth_error(
            auth_type='basic',
            system_name='PRD',
            host='prd.sap.example.com',
            original_error=err,
            is_retry=True,
        )
        assert "after retry" in msg
        assert "PRD" in msg


class TestFormatConnectionError:
    """Tests for format_connection_error."""

    def test_includes_host_and_port(self):
        err = Exception("Connection refused")
        messages = format_connection_error(
            host='dev.sap.example.com',
            port=44300,
            ssl=True,
            original_error=err,
            service_type='ADT',
        )
        assert any("dev.sap.example.com:44300" in m for m in messages)

    def test_includes_service_type(self):
        err = Exception("Timeout")
        messages = format_connection_error(
            host='host.example.com',
            port=443,
            ssl=True,
            original_error=err,
            service_type='gCTS',
        )
        assert any("gCTS" in m for m in messages)

    def test_suggests_vpn_check(self):
        err = Exception("Connection refused")
        messages = format_connection_error(
            host='host.example.com',
            port=443,
            ssl=True,
            original_error=err,
        )
        assert any("VPN" in m or "network" in m for m in messages)

    def test_ssl_enabled_hint(self):
        err = Exception("SSL error")
        messages = format_connection_error(
            host='host.example.com',
            port=443,
            ssl=True,
            original_error=err,
        )
        assert any("SSL" in m or "HTTPS" in m for m in messages)

    def test_ssl_disabled_hint(self):
        err = Exception("Connection reset")
        messages = format_connection_error(
            host='host.example.com',
            port=8000,
            ssl=False,
            original_error=err,
        )
        combined = ' '.join(messages).lower()
        assert "https" in combined

    def test_includes_original_error(self):
        err = Exception("Connection refused")
        messages = format_connection_error(
            host='host.example.com',
            port=443,
            ssl=True,
            original_error=err,
        )
        assert "Connection refused" in messages[-1]

    def test_returns_list(self):
        err = Exception("error")
        messages = format_connection_error(
            host='h', port=443, ssl=True, original_error=err,
        )
        assert isinstance(messages, list)
        assert len(messages) >= 1


class TestFormatCommandError:
    """Tests for format_command_error."""

    def test_includes_tool_name(self):
        err = Exception("Object not found")
        msg = format_command_error(tool_name='abap_class_read', original_error=err)
        assert "abap_class_read" in msg

    def test_includes_original_error(self):
        err = Exception("Object not found")
        msg = format_command_error(tool_name='abap_class_read', original_error=err)
        assert "Object not found" in msg


class TestFormatStartupError:
    """Tests for format_startup_error."""

    def test_config_error(self):
        from sapclimcp.config import ConfigError
        err = ConfigError("Missing 'systems' key")
        msg = format_startup_error(err)
        assert "configuration error" in msg
        assert "Missing 'systems' key" in msg
        assert "config file" in msg

    def test_import_error(self):
        err = ImportError("No module named 'sap'")
        msg = format_startup_error(err)
        assert "missing dependency" in msg
        assert "No module named 'sap'" in msg
        assert "install" in msg

    def test_generic_error(self):
        err = RuntimeError("something broke")
        msg = format_startup_error(err)
        assert "unexpected error" in msg
        assert "RuntimeError" in msg
        assert "something broke" in msg
        assert "bug" in msg
