"""
Server-side system configuration for mcp-sapcli.

Loads named SAP system definitions from a JSON config file,
resolves ``$ENV_VAR`` references from environment variables,
and manages cached connections per system.
"""

import json
import os
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Optional

import requests

import sap.adt
import sap.cli


_ENV_VAR_RE = re.compile(r'^\$([A-Za-z_][A-Za-z0-9_]*)$')


class ConfigError(Exception):
    """Raised for configuration loading or validation errors."""


_VALID_AUTH_TYPES = frozenset({'basic', 'cookie'})


@dataclass
class SystemConfig:
    """Connection settings for a single SAP system."""

    ashost: str
    client: str
    port: int = 443
    ssl: bool = True
    verify: bool = True
    auth: str = 'basic'

    # basic auth
    user: str = ''
    # password can be empty (some SAP dev systems allow passwordless accounts)
    password: str = ''

    # cookie auth
    cookie: str = ''

    def __post_init__(self) -> None:
        if self.auth not in _VALID_AUTH_TYPES:
            raise ConfigError(
                f"Invalid auth type '{self.auth}'. "
                f"Must be one of: {', '.join(sorted(_VALID_AUTH_TYPES))}"
            )
        if self.auth == 'cookie' and not self.cookie:
            raise ConfigError(
                "Cookie auth requires a non-empty 'cookie' field"
            )
        if self.auth == 'basic' and not self.user:
            raise ConfigError(
                "Basic auth requires a non-empty 'user' field"
            )


@dataclass
class ServerConfig:
    """Top-level server configuration holding named systems."""

    systems: dict[str, SystemConfig] = field(default_factory=dict)
    default_system: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.systems:
            raise ConfigError('At least one system must be configured')

        if self.default_system and self.default_system not in self.systems:
            raise ConfigError(
                f"Default system '{self.default_system}' not found in systems: "
                f"{', '.join(self.systems.keys())}"
            )

        # If only one system, make it the default
        if len(self.systems) == 1 and self.default_system is None:
            self.default_system = next(iter(self.systems))


def _resolve_env_vars(value: Any) -> Any:
    """Resolve ``$ENV_VAR`` references in string values."""

    if not isinstance(value, str):
        return value

    match = _ENV_VAR_RE.match(value)
    if not match:
        return value

    var_name = match.group(1)
    env_value = os.environ.get(var_name)
    if env_value is None:
        raise ConfigError(
            f"Environment variable '{var_name}' referenced in config is not set"
        )
    return env_value


def load_config(path: str) -> ServerConfig:
    """Load server configuration from a JSON file.

    String values matching ``$ENV_VAR`` are replaced with the
    corresponding environment variable at load time.

    Args:
        path: Path to the JSON configuration file.

    Returns:
        Parsed and validated ServerConfig.

    Raises:
        ConfigError: If the file cannot be read, parsed, or validated.
    """

    try:
        with open(path, encoding='utf-8') as fobj:
            raw = json.load(fobj)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f'Failed to load config from {path}: {exc}') from exc

    if not isinstance(raw, dict):
        raise ConfigError('Config must be a JSON object')

    raw_systems = raw.get('systems')
    if not isinstance(raw_systems, dict):
        raise ConfigError("Config must have a 'systems' object")

    systems: dict[str, SystemConfig] = {}
    for name, sys_raw in raw_systems.items():
        if not isinstance(sys_raw, dict):
            raise ConfigError(f"System '{name}' must be a JSON object")

        resolved = {k: _resolve_env_vars(v) for k, v in sys_raw.items()}
        try:
            systems[name] = SystemConfig(**resolved)
        except (TypeError, ConfigError) as exc:
            raise ConfigError(
                f"System '{name}': {exc}"
            ) from exc

    default_system = raw.get('default_system')
    if default_system is not None:
        default_system = str(default_system)

    return ServerConfig(systems=systems, default_system=default_system)


class ConnectionManager:
    """Manages cached SAP connections per system and connection type.

    Connections are created lazily on first use and reused for
    subsequent calls to the same system with the same connection type.

    Note: the cache has no TTL or invalidation. If a cookie expires
    mid-session, subsequent calls will fail until the server is
    restarted with a fresh cookie. Cache invalidation and retry
    logic is planned as a future enhancement.

    Note: the cache is not thread-safe. In stdio mode this is moot
    (single-threaded). In HTTP mode, concurrent requests for the same
    uncached system may create duplicate connections; the last write
    wins and the other connection object is discarded. This is benign
    since connections are lightweight and produce identical results.
    """

    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._cache: dict[tuple[str, str], Any] = {}

    @property
    def system_names(self) -> list[str]:
        """List of configured system names."""
        return list(self._config.systems.keys())

    @property
    def default_system(self) -> Optional[str]:
        """Default system name, if set."""
        return self._config.default_system

    def _resolve_system(self, system_name: Optional[str]) -> SystemConfig:
        """Resolve a system name to its configuration.

        Args:
            system_name: Explicit system name or None for default.

        Returns:
            The SystemConfig for the resolved system.

        Raises:
            ConfigError: If the system cannot be resolved.
        """

        if system_name is None:
            system_name = self._config.default_system

        if system_name is None:
            raise ConfigError(
                'No system specified and no default_system configured. '
                f'Available systems: {", ".join(self.system_names)}'
            )

        sys_config = self._config.systems.get(system_name)
        if sys_config is None:
            raise ConfigError(
                f"Unknown system '{system_name}'. "
                f'Available systems: {", ".join(self.system_names)}'
            )

        return sys_config

    def _make_connection_args(self, sys_config: SystemConfig) -> SimpleNamespace:
        """Build a SimpleNamespace matching what sapcli connection factories expect."""

        return SimpleNamespace(
            ashost=sys_config.ashost,
            client=sys_config.client,
            port=sys_config.port,
            ssl=sys_config.ssl,
            verify=sys_config.verify,
            # sapcli requires non-empty user/password to construct
            # the Connection object even when cookie auth is used
            user=sys_config.user or 'dummy',
            password=sys_config.password or 'dummy',
            ssl_server_cert=None,
        )

    def _create_adt_connection(self, sys_config: SystemConfig) -> sap.adt.Connection:
        """Create an ADT connection, optionally applying cookie auth."""

        args = self._make_connection_args(sys_config)
        conn = sap.cli.adt_connection_from_args(args)

        if sys_config.auth == 'cookie':
            # Inject cookie auth by patching the HTTP client's build_session
            # to set cookies and remove basic auth before the first request.
            # This is necessary because sapcli's build_session() authenticates
            # during session creation (CSRF token fetch).
            # Uses private APIs on sap.adt.Connection — tested against sapcli 1.x,
            # may need updating if internals change.
            if not hasattr(conn, '_http_client'):
                raise ConfigError(
                    'Cookie auth requires sap.adt.Connection._http_client. '
                    'This sapcli version may not be compatible.'
                )
            http_client = conn._http_client
            cookie_value = sys_config.cookie

            # Mirrors sap.http.client.HTTPClient.build_session() from sapcli 1.x
            # (sap/http/client.py:190-215) but replaces basic auth with cookie auth.
            # Must be kept in sync with upstream changes to build_session().
            def cookie_build_session():
                session = requests.Session()
                session.auth = None
                session.headers['Cookie'] = cookie_value

                if http_client.ssl_server_cert:
                    session.verify = http_client.ssl_server_cert
                elif http_client.ssl_verify is False:
                    import urllib3
                    urllib3.disable_warnings()
                    session.verify = False

                login_headers = {'x-csrf-token': 'Fetch'}
                response = http_client.execute_with_session(
                    session, http_client.login_method,
                    http_client.login_path, headers=login_headers,
                )

                if 'x-csrf-token' in response.headers:
                    session.headers.update({
                        'x-csrf-token': response.headers['x-csrf-token']
                    })

                return session, response

            http_client.build_session = cookie_build_session

        return conn

    def _create_gcts_connection(self, sys_config: SystemConfig) -> Any:
        """Create a gCTS connection."""

        if sys_config.auth == 'cookie':
            raise ConfigError(
                'Cookie auth is not supported for gCTS connections. '
                'Use basic auth for gCTS systems.'
            )

        args = self._make_connection_args(sys_config)
        return sap.cli.gcts_connection_from_args(args)

    def get_connection(
        self,
        system_name: Optional[str],
        conn_factory: Callable,
    ) -> Any:
        """Get or create a cached connection for the given system.

        Args:
            system_name: System name or None for default.
            conn_factory: The sapcli connection factory function
                (used to determine connection type).

        Returns:
            A cached or newly created connection.

        Raises:
            ConfigError: If the system cannot be resolved or
                the connection type is not supported.
        """

        sys_config = self._resolve_system(system_name)
        resolved_name = system_name or self._config.default_system

        # Determine connection type from factory
        if conn_factory == sap.cli.adt_connection_from_args:
            conn_type = 'adt'
        elif conn_factory == sap.cli.gcts_connection_from_args:
            conn_type = 'gcts'
        else:
            raise ConfigError(
                f"Unsupported connection factory: {conn_factory}. "
                "Only ADT and gCTS connections are supported."
            )

        cache_key = (resolved_name, conn_type)
        if cache_key not in self._cache:
            if conn_type == 'adt':
                self._cache[cache_key] = self._create_adt_connection(sys_config)
            else:
                self._cache[cache_key] = self._create_gcts_connection(sys_config)

        return self._cache[cache_key]
