"""Tests for sapclimcp.config — server-side system configuration."""

import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import sap.cli

from sapclimcp.config import (
    ConfigError,
    ConnectionManager,
    ServerConfig,
    SystemConfig,
    load_config,
    _resolve_env_vars,
)


# ---------------------------------------------------------------------------
# _resolve_env_vars
# ---------------------------------------------------------------------------


class TestResolveEnvVars:
    def test_non_string_passthrough(self):
        assert _resolve_env_vars(42) == 42
        assert _resolve_env_vars(True) is True

    def test_plain_string_passthrough(self):
        assert _resolve_env_vars('hello') == 'hello'

    def test_env_var_resolved(self, monkeypatch):
        monkeypatch.setenv('MY_SECRET', 'resolved_value')
        assert _resolve_env_vars('$MY_SECRET') == 'resolved_value'

    def test_env_var_missing_raises(self):
        # Ensure the var does not exist
        os.environ.pop('NONEXISTENT_VAR_12345', None)
        with pytest.raises(ConfigError, match='NONEXISTENT_VAR_12345'):
            _resolve_env_vars('$NONEXISTENT_VAR_12345')

    def test_not_env_ref_if_mid_string(self):
        """$VAR must be the entire string to be treated as a reference."""
        assert _resolve_env_vars('prefix_$VAR') == 'prefix_$VAR'


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def _write_json(data: dict) -> str:
    """Write data to a temp JSON file and return the path."""
    fd, path = tempfile.mkstemp(suffix='.json')
    with os.fdopen(fd, 'w', encoding='utf-8') as fobj:
        json.dump(data, fobj)
    return path


class TestLoadConfig:
    def test_basic_single_system(self):
        path = _write_json({
            'systems': {
                'DEV': {
                    'ashost': 'dev.example.com',
                    'client': '100',
                    'port': 443,
                    'user': 'admin',
                }
            }
        })
        try:
            cfg = load_config(path)
            assert 'DEV' in cfg.systems
            assert cfg.systems['DEV'].ashost == 'dev.example.com'
            assert cfg.default_system == 'DEV'  # auto-default for single system
        finally:
            os.unlink(path)

    def test_env_var_resolution(self, monkeypatch):
        monkeypatch.setenv('TEST_SAP_USER', 'admin')
        monkeypatch.setenv('TEST_SAP_PASS', 's3cret')
        path = _write_json({
            'systems': {
                'DEV': {
                    'ashost': 'dev.example.com',
                    'client': '100',
                    'auth': 'basic',
                    'user': '$TEST_SAP_USER',
                    'password': '$TEST_SAP_PASS',
                }
            }
        })
        try:
            cfg = load_config(path)
            assert cfg.systems['DEV'].user == 'admin'
            assert cfg.systems['DEV'].password == 's3cret'
        finally:
            os.unlink(path)

    def test_multi_system_with_default(self):
        path = _write_json({
            'systems': {
                'DEV': {'ashost': 'dev.example.com', 'client': '100', 'user': 'u'},
                'QA': {'ashost': 'qa.example.com', 'client': '200', 'user': 'u'},
            },
            'default_system': 'DEV',
        })
        try:
            cfg = load_config(path)
            assert len(cfg.systems) == 2
            assert cfg.default_system == 'DEV'
        finally:
            os.unlink(path)

    def test_multi_system_no_default(self):
        path = _write_json({
            'systems': {
                'DEV': {'ashost': 'dev.example.com', 'client': '100', 'user': 'u'},
                'QA': {'ashost': 'qa.example.com', 'client': '200', 'user': 'u'},
            },
        })
        try:
            cfg = load_config(path)
            assert cfg.default_system is None
        finally:
            os.unlink(path)

    def test_bad_default_system_raises(self):
        path = _write_json({
            'systems': {
                'DEV': {'ashost': 'dev.example.com', 'client': '100', 'user': 'u'},
            },
            'default_system': 'NONEXISTENT',
        })
        try:
            with pytest.raises(ConfigError, match='NONEXISTENT'):
                load_config(path)
        finally:
            os.unlink(path)

    def test_empty_systems_raises(self):
        path = _write_json({'systems': {}})
        try:
            with pytest.raises(ConfigError, match='At least one system'):
                load_config(path)
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with pytest.raises(ConfigError, match='Failed to load'):
            load_config('/nonexistent/path.json')

    def test_invalid_json_raises(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as fobj:
            fobj.write('not json{{{')
        try:
            with pytest.raises(ConfigError, match='Failed to load'):
                load_config(path)
        finally:
            os.unlink(path)

    def test_cookie_auth_system(self, monkeypatch):
        monkeypatch.setenv('MY_COOKIE', 'SAP_SESSIONID=abc123')
        path = _write_json({
            'systems': {
                'I7D': {
                    'ashost': 'i7d.example.com',
                    'client': '001',
                    'auth': 'cookie',
                    'cookie': '$MY_COOKIE',
                }
            }
        })
        try:
            cfg = load_config(path)
            assert cfg.systems['I7D'].auth == 'cookie'
            assert cfg.systems['I7D'].cookie == 'SAP_SESSIONID=abc123'
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# ServerConfig
# ---------------------------------------------------------------------------


class TestServerConfig:
    def test_single_system_auto_default(self):
        cfg = ServerConfig(systems={'DEV': SystemConfig(ashost='h', client='c', user='u')})
        assert cfg.default_system == 'DEV'

    def test_multi_system_no_auto_default(self):
        cfg = ServerConfig(systems={
            'A': SystemConfig(ashost='a', client='1', user='u'),
            'B': SystemConfig(ashost='b', client='2', user='u'),
        })
        assert cfg.default_system is None


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------


class TestConnectionManager:

    @staticmethod
    def _make_manager(**overrides) -> ConnectionManager:
        sys_config = SystemConfig(
            ashost='test.example.com',
            client='100',
            port=443,
            user='admin',
            password='secret',
            **overrides,
        )
        cfg = ServerConfig(systems={'DEV': sys_config}, default_system='DEV')
        return ConnectionManager(cfg)

    def test_system_names(self):
        mgr = self._make_manager()
        assert mgr.system_names == ['DEV']

    def test_default_system(self):
        mgr = self._make_manager()
        assert mgr.default_system == 'DEV'

    @patch('sap.cli.adt_connection_from_args')
    def test_get_adt_connection(self, mock_factory):
        mock_conn = MagicMock()
        mock_factory.return_value = mock_conn

        mgr = self._make_manager()
        conn = mgr.get_connection('DEV', sap.cli.adt_connection_from_args)

        assert conn is mock_conn
        mock_factory.assert_called_once()

        # Verify connection args
        call_args = mock_factory.call_args[0][0]
        assert call_args.ashost == 'test.example.com'
        assert call_args.client == '100'

    @patch('sap.cli.adt_connection_from_args')
    def test_connection_caching(self, mock_factory):
        mock_factory.return_value = MagicMock()

        mgr = self._make_manager()
        conn1 = mgr.get_connection('DEV', sap.cli.adt_connection_from_args)
        conn2 = mgr.get_connection('DEV', sap.cli.adt_connection_from_args)

        assert conn1 is conn2
        assert mock_factory.call_count == 1  # Only created once

    @patch('sap.cli.adt_connection_from_args')
    def test_default_system_resolution(self, mock_factory):
        mock_factory.return_value = MagicMock()

        mgr = self._make_manager()
        conn = mgr.get_connection(None, sap.cli.adt_connection_from_args)

        assert conn is not None
        mock_factory.assert_called_once()

    def test_unknown_system_raises(self):
        mgr = self._make_manager()
        with pytest.raises(ConfigError, match='Unknown system'):
            mgr.get_connection('NONEXISTENT', sap.cli.adt_connection_from_args)

    def test_no_default_no_system_raises(self):
        cfg = ServerConfig(
            systems={
                'A': SystemConfig(ashost='a', client='1', user='u'),
                'B': SystemConfig(ashost='b', client='2', user='u'),
            },
        )
        mgr = ConnectionManager(cfg)
        with pytest.raises(ConfigError, match='No system specified'):
            mgr.get_connection(None, sap.cli.adt_connection_from_args)

    @patch('sap.cli.adt_connection_from_args')
    def test_cookie_auth_patches_build_session(self, mock_factory):
        """Cookie auth replaces build_session on the HTTP client."""
        mock_conn = MagicMock()
        mock_http_client = MagicMock()
        mock_conn._http_client = mock_http_client
        mock_factory.return_value = mock_conn

        mgr = self._make_manager(auth='cookie', cookie='SAP_SESSION=abc')
        mgr.get_connection('DEV', sap.cli.adt_connection_from_args)

        # build_session should have been replaced with our cookie version
        assert mock_http_client.build_session != mock_http_client.build_session.__class__

    @patch('sap.cli.gcts_connection_from_args')
    def test_get_gcts_connection(self, mock_factory):
        mock_conn = MagicMock()
        mock_factory.return_value = mock_conn

        mgr = self._make_manager()
        conn = mgr.get_connection('DEV', sap.cli.gcts_connection_from_args)

        assert conn is mock_conn

    def test_unsupported_factory_raises(self):
        mgr = self._make_manager()
        with pytest.raises(ConfigError, match='Unsupported connection factory'):
            mgr.get_connection('DEV', lambda args: None)

    def test_gcts_cookie_auth_raises(self):
        mgr = self._make_manager(auth='cookie', cookie='SAP_SESSION=abc')
        with pytest.raises(ConfigError, match='not supported for gCTS'):
            mgr.get_connection('DEV', sap.cli.gcts_connection_from_args)

    @patch('sap.cli.adt_connection_from_args')
    def test_hasattr_guard_on_http_client(self, mock_factory):
        """ConfigError raised when connection lacks _http_client."""
        mock_conn = MagicMock(spec=[])  # empty spec — no _http_client
        mock_factory.return_value = mock_conn

        mgr = self._make_manager(auth='cookie', cookie='SAP_SESSION=abc')
        with pytest.raises(ConfigError, match='_http_client'):
            mgr.get_connection('DEV', sap.cli.adt_connection_from_args)


# ---------------------------------------------------------------------------
# SystemConfig validation
# ---------------------------------------------------------------------------


class TestSystemConfigValidation:

    def test_invalid_auth_type_raises(self):
        with pytest.raises(ConfigError, match="Invalid auth type 'cookies'"):
            SystemConfig(ashost='h', client='c', auth='cookies')

    def test_cookie_auth_without_cookie_raises(self):
        with pytest.raises(ConfigError, match='non-empty'):
            SystemConfig(ashost='h', client='c', auth='cookie', cookie='')

    def test_basic_auth_without_user_raises(self):
        with pytest.raises(ConfigError, match='non-empty'):
            SystemConfig(ashost='h', client='c', auth='basic', user='')

    def test_valid_basic_auth(self):
        cfg = SystemConfig(ashost='h', client='c', user='admin', password='pass')
        assert cfg.auth == 'basic'

    def test_valid_cookie_auth(self):
        cfg = SystemConfig(ashost='h', client='c', auth='cookie', cookie='SAP=abc')
        assert cfg.auth == 'cookie'
