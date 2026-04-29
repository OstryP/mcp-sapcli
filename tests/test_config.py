"""Tests for sapclimcp.config — server-side system configuration."""

import json
import os
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


def _write_json(tmp_path, data: dict) -> str:
    """Write data to a JSON file in tmp_path and return the path string."""
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return str(path)


class TestLoadConfig:
    def test_basic_single_system(self, tmp_path):
        path = _write_json(tmp_path, {
            'systems': {
                'DEV': {
                    'ashost': 'dev.example.com',
                    'client': '100',
                    'port': 443,
                    'user': 'admin',
                }
            }
        })
        cfg = load_config(path)
        assert 'DEV' in cfg.systems
        assert cfg.systems['DEV'].ashost == 'dev.example.com'
        assert cfg.default_system == 'DEV'  # auto-default for single system

    def test_env_var_resolution(self, monkeypatch, tmp_path):
        monkeypatch.setenv('TEST_SAP_USER', 'admin')
        monkeypatch.setenv('TEST_SAP_PASS', 's3cret')
        path = _write_json(tmp_path, {
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
        cfg = load_config(path)
        assert cfg.systems['DEV'].user == 'admin'
        assert cfg.systems['DEV'].password == 's3cret'

    def test_multi_system_with_default(self, tmp_path):
        path = _write_json(tmp_path, {
            'systems': {
                'DEV': {'ashost': 'dev.example.com', 'client': '100', 'user': 'u'},
                'QA': {'ashost': 'qa.example.com', 'client': '200', 'user': 'u'},
            },
            'default_system': 'DEV',
        })
        cfg = load_config(path)
        assert len(cfg.systems) == 2
        assert cfg.default_system == 'DEV'

    def test_multi_system_no_default(self, tmp_path):
        path = _write_json(tmp_path, {
            'systems': {
                'DEV': {'ashost': 'dev.example.com', 'client': '100', 'user': 'u'},
                'QA': {'ashost': 'qa.example.com', 'client': '200', 'user': 'u'},
            },
        })
        cfg = load_config(path)
        assert cfg.default_system is None

    def test_bad_default_system_raises(self, tmp_path):
        path = _write_json(tmp_path, {
            'systems': {
                'DEV': {'ashost': 'dev.example.com', 'client': '100', 'user': 'u'},
            },
            'default_system': 'NONEXISTENT',
        })
        with pytest.raises(ConfigError, match='NONEXISTENT'):
            load_config(path)

    def test_empty_systems_raises(self, tmp_path):
        path = _write_json(tmp_path, {'systems': {}})
        with pytest.raises(ConfigError, match='At least one system'):
            load_config(path)

    def test_missing_file_raises(self):
        with pytest.raises(ConfigError, match='Failed to load'):
            load_config('/nonexistent/path.json')

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / 'bad.json'
        path.write_text('not json{{{')
        with pytest.raises(ConfigError, match='Failed to load'):
            load_config(str(path))

    def test_cookie_auth_system(self, monkeypatch, tmp_path):
        monkeypatch.setenv('MY_COOKIE', 'SAP_SESSIONID=abc123')
        path = _write_json(tmp_path, {
            'systems': {
                'I7D': {
                    'ashost': 'i7d.example.com',
                    'client': '001',
                    'auth': 'cookie',
                    'cookie': '$MY_COOKIE',
                }
            }
        })
        cfg = load_config(path)
        assert cfg.systems['I7D'].auth == 'cookie'
        assert cfg.systems['I7D'].cookie == 'SAP_SESSIONID=abc123'


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
        conn = mgr.get_connection('DEV', 'adt')

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
        conn1 = mgr.get_connection('DEV', 'adt')
        conn2 = mgr.get_connection('DEV', 'adt')

        assert conn1 is conn2
        assert mock_factory.call_count == 1  # Only created once

    @patch('sap.cli.adt_connection_from_args')
    def test_default_system_resolution(self, mock_factory):
        mock_factory.return_value = MagicMock()

        mgr = self._make_manager()
        conn = mgr.get_connection(None, 'adt')

        assert conn is not None
        mock_factory.assert_called_once()

    def test_unknown_system_raises(self):
        mgr = self._make_manager()
        with pytest.raises(ConfigError, match='Unknown system'):
            mgr.get_connection('NONEXISTENT', 'adt')

    def test_no_default_no_system_raises(self):
        cfg = ServerConfig(
            systems={
                'A': SystemConfig(ashost='a', client='1', user='u'),
                'B': SystemConfig(ashost='b', client='2', user='u'),
            },
        )
        mgr = ConnectionManager(cfg)
        with pytest.raises(ConfigError, match='No system specified'):
            mgr.get_connection(None, 'adt')

    @patch('sap.cli.adt_connection_from_args')
    def test_cookie_auth_patches_build_session(self, mock_factory):
        """Cookie auth replaces build_session and injects cookie header."""
        mock_conn = MagicMock()
        mock_http_client = MagicMock()
        mock_http_client.ssl_server_cert = None
        mock_http_client.ssl_verify = False

        mock_response = MagicMock()
        mock_response.headers = {'x-csrf-token': 'test-csrf-token'}
        mock_http_client.execute_with_session.return_value = mock_response

        mock_conn._http_client = mock_http_client
        original_build_session = mock_http_client.build_session
        mock_factory.return_value = mock_conn

        mgr = self._make_manager(auth='cookie', cookie='SAP_SESSION=abc')
        mgr.get_connection('DEV', 'adt')

        # build_session was replaced with our cookie version
        assert mock_http_client.build_session is not original_build_session
        assert callable(mock_http_client.build_session)

        # Call the patched build_session and verify behavior
        session, response = mock_http_client.build_session()
        assert session.auth is None
        assert session.headers['Cookie'] == 'SAP_SESSION=abc'
        assert session.headers['x-csrf-token'] == 'test-csrf-token'

    @patch('sap.cli.gcts_connection_from_args')
    def test_get_gcts_connection(self, mock_factory):
        mock_conn = MagicMock()
        mock_factory.return_value = mock_conn

        mgr = self._make_manager()
        conn = mgr.get_connection('DEV', 'gcts')

        assert conn is mock_conn

    def test_unsupported_conn_type_raises(self):
        mgr = self._make_manager()
        with pytest.raises(ConfigError, match='Unsupported connection type'):
            mgr.get_connection('DEV', 'odata')

    def test_gcts_cookie_auth_raises(self):
        mgr = self._make_manager(auth='cookie', cookie='SAP_SESSION=abc')
        with pytest.raises(ConfigError, match='not supported for gCTS'):
            mgr.get_connection('DEV', 'gcts')

    @patch('sap.cli.adt_connection_from_args')
    def test_hasattr_guard_on_http_client(self, mock_factory):
        """ConfigError raised when connection lacks _http_client."""
        mock_conn = MagicMock(spec=[])  # empty spec — no _http_client
        mock_factory.return_value = mock_conn

        mgr = self._make_manager(auth='cookie', cookie='SAP_SESSION=abc')
        with pytest.raises(ConfigError, match='_http_client'):
            mgr.get_connection('DEV', 'adt')


# ---------------------------------------------------------------------------
# ConnectionManager — TTL and eviction
# ---------------------------------------------------------------------------


class TestConnectionManagerTTL:

    @staticmethod
    def _make_manager(cache_ttl_seconds=3600, **overrides) -> ConnectionManager:
        sys_config = SystemConfig(
            ashost='test.example.com',
            client='100',
            port=443,
            user='admin',
            password='secret',
            **overrides,
        )
        cfg = ServerConfig(systems={'DEV': sys_config}, default_system='DEV')
        return ConnectionManager(cfg, cache_ttl_seconds=cache_ttl_seconds)

    @patch('sapclimcp.config.time.monotonic')
    @patch('sap.cli.adt_connection_from_args')
    def test_ttl_expired_connection_recreated(self, mock_factory, mock_time):
        """After TTL expires, get_connection must create a new connection."""
        conn_first = MagicMock(name='conn_first')
        conn_second = MagicMock(name='conn_second')
        mock_factory.side_effect = [conn_first, conn_second]

        mgr = self._make_manager(cache_ttl_seconds=300)

        mock_time.return_value = 1000.0
        result1 = mgr.get_connection('DEV', 'adt')
        assert result1 is conn_first

        # Advance past TTL
        mock_time.return_value = 1301.0
        result2 = mgr.get_connection('DEV', 'adt')
        assert result2 is conn_second
        assert result2 is not result1
        assert mock_factory.call_count == 2

    @patch('sapclimcp.config.time.monotonic')
    @patch('sap.cli.adt_connection_from_args')
    def test_ttl_not_expired_returns_cached(self, mock_factory, mock_time):
        """Before TTL expires, the same cached connection is returned."""
        mock_factory.return_value = MagicMock()

        mgr = self._make_manager(cache_ttl_seconds=300)

        mock_time.return_value = 1000.0
        conn1 = mgr.get_connection('DEV', 'adt')

        # Advance but NOT past TTL
        mock_time.return_value = 1299.0
        conn2 = mgr.get_connection('DEV', 'adt')

        assert conn1 is conn2
        assert mock_factory.call_count == 1

    @patch('sap.cli.adt_connection_from_args')
    def test_evict_removes_cached_connection(self, mock_factory):
        """After evict(), the next get_connection creates a fresh connection."""
        conn_first = MagicMock(name='conn_first')
        conn_second = MagicMock(name='conn_second')
        mock_factory.side_effect = [conn_first, conn_second]

        mgr = self._make_manager()
        result1 = mgr.get_connection('DEV', 'adt')
        assert result1 is conn_first

        mgr.evict('DEV', 'adt')

        result2 = mgr.get_connection('DEV', 'adt')
        assert result2 is conn_second
        assert mock_factory.call_count == 2

    def test_evict_noop_for_uncached(self):
        """Evicting a connection that was never cached does not raise."""
        mgr = self._make_manager()
        mgr.evict('DEV', 'adt')

    @patch('sap.cli.adt_connection_from_args')
    def test_evict_none_system_uses_default(self, mock_factory):
        """evict(None, factory) resolves to the default system."""
        conn_first = MagicMock(name='conn_first')
        conn_second = MagicMock(name='conn_second')
        mock_factory.side_effect = [conn_first, conn_second]

        mgr = self._make_manager()
        mgr.get_connection(None, 'adt')

        mgr.evict(None, 'adt')

        result = mgr.get_connection(None, 'adt')
        assert result is conn_second
        assert mock_factory.call_count == 2

    @patch('sapclimcp.config.time.monotonic')
    @patch('sap.cli.adt_connection_from_args')
    def test_custom_ttl(self, mock_factory, mock_time):
        """A short custom TTL triggers recreation sooner."""
        conn_first = MagicMock(name='conn_first')
        conn_second = MagicMock(name='conn_second')
        mock_factory.side_effect = [conn_first, conn_second]

        mgr = self._make_manager(cache_ttl_seconds=60)

        mock_time.return_value = 0.0
        mgr.get_connection('DEV', 'adt')

        mock_time.return_value = 60.0
        result = mgr.get_connection('DEV', 'adt')
        assert result is conn_second

    def test_evict_unsupported_conn_type_is_noop(self):
        """Evicting with an unrecognized conn_type does not raise."""
        mgr = self._make_manager()
        mgr.evict('DEV', 'odata')

    def test_evict_none_system_no_default_is_noop(self):
        """evict(None, factory) is a no-op when no default_system is configured."""
        sys_a = SystemConfig(
            ashost='a.example.com', client='100', port=443,
            user='admin', password='secret',
        )
        sys_b = SystemConfig(
            ashost='b.example.com', client='200', port=443,
            user='admin', password='secret',
        )
        cfg = ServerConfig(systems={'A': sys_a, 'B': sys_b})
        assert cfg.default_system is None
        mgr = ConnectionManager(cfg)
        mgr.evict(None, 'adt')


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
