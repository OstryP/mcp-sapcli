"""
Server-side system configuration for mcp-sapcli.

Loads named SAP system definitions from a JSON config file,
resolves ``$ENV_VAR`` references from environment variables,
and manages cached connections per system.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

import requests

import sap.adt
import sap.cli
from sap.http.errors import UnauthorizedError


_LOGGER = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r'^\$([A-Za-z_][A-Za-z0-9_]*)$')


class ConfigError(Exception):
    """Raised for configuration loading or validation errors."""


class CookieSessionInitializer:
    """HTTPSessionInitializer that authenticates via pre-existing SSO cookies.

    Implements the sap.http.client.HTTPSessionInitializer protocol so that
    sapcli uses cookie-based auth instead of basic auth for the session.
    """

    def __init__(self, cookie: str) -> None:
        self._cookie = cookie

    def initialize_session(self, session: requests.Session) -> requests.Session:
        session.auth = None
        session.headers['Cookie'] = self._cookie
        return session

    def build_unauthorized_error(self, req, res) -> UnauthorizedError:
        return UnauthorizedError(req, res, 'cookie-auth')


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


DEFAULT_CACHE_TTL = 3600


@dataclass(slots=True)
class _CacheEntry:
    """A cached connection with its creation timestamp."""

    connection: Any
    created_at: float


class ConnectionManager:
    """Manages cached SAP connections per system and connection type.

    Connections are created lazily on first use and reused for
    subsequent calls to the same system with the same connection type.

    Cached connections expire after ``cache_ttl_seconds`` (default 1 hour).
    When a TTL-expired entry is requested, it is discarded and a fresh
    connection is created transparently.  Set ``cache_ttl_seconds=0`` to
    disable caching (every call creates a fresh connection).  The
    ``evict()`` method allows callers to force immediate removal
    (e.g. after an auth failure).

    Note: the cache is not thread-safe. In stdio mode this is moot
    (single-threaded). In HTTP mode, concurrent requests for the same
    uncached system may create duplicate connections; the last write
    wins and the other connection object is discarded. This is benign
    since connections are lightweight and produce identical results.
    """

    # Connectable subset — types this manager can actually serve.
    # Broader types (rfc, odata) may be registered on tools but are
    # not yet supported for server-managed connections.
    _SUPPORTED_CONN_TYPES = frozenset({'adt', 'gcts'})

    def __init__(
        self,
        config: ServerConfig,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL,
    ) -> None:
        self._config = config
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._cache_ttl = cache_ttl_seconds

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
            user=sys_config.user or 'unused',
            password=sys_config.password or 'unused',
            ssl_server_cert=None,
        )

    def _create_adt_connection(self, sys_config: SystemConfig) -> sap.adt.Connection:
        """Create an ADT connection, using session_initializer for cookie auth."""

        initializer = None
        if sys_config.auth == 'cookie':
            initializer = CookieSessionInitializer(sys_config.cookie)

        return sap.adt.Connection(
            host=sys_config.ashost,
            client=sys_config.client,
            user=sys_config.user or 'cookie-auth',
            password=sys_config.password or 'unused',
            port=sys_config.port,
            ssl=sys_config.ssl,
            verify=sys_config.verify,
            session_initializer=initializer,
        )

    def _create_gcts_connection(self, sys_config: SystemConfig) -> Any:
        """Create a gCTS connection."""

        if sys_config.auth == 'cookie':
            raise ConfigError(
                'Cookie auth is not supported for gCTS connections. '
                'Use basic auth for gCTS systems.'
            )

        args = self._make_connection_args(sys_config)
        return sap.cli.gcts_connection_from_args(args)

    def evict(
        self,
        system_name: Optional[str],
        conn_type: str,
    ) -> None:
        """Remove a cached connection, forcing recreation on next access.

        Unlike ``get_connection``, this method does not validate
        ``conn_type`` — it silently no-ops for unknown types to avoid
        raising during error recovery paths.

        Args:
            system_name: System name or None for default.
            conn_type: Connection type string ('adt' or 'gcts').
        """

        resolved_name = system_name or self._config.default_system
        if resolved_name is None:
            return

        if resolved_name not in self._config.systems:
            _LOGGER.debug("evict: system '%s' not in config, skipping", resolved_name)
            return

        self._cache.pop((resolved_name, conn_type), None)

    def get_connection(
        self,
        system_name: Optional[str],
        conn_type: str,
    ) -> Any:
        """Get or create a cached connection for the given system.

        Returns a cached connection if one exists and has not exceeded
        the TTL. Otherwise creates a fresh connection and caches it.

        Args:
            system_name: System name or None for default.
            conn_type: Connection type string ('adt' or 'gcts').

        Returns:
            A cached or newly created connection.

        Raises:
            ConfigError: If the system cannot be resolved or
                the connection type is not supported.
        """

        if conn_type not in self._SUPPORTED_CONN_TYPES:
            raise ConfigError(
                f"Unsupported connection type '{conn_type}'. "
                f"Supported: {', '.join(sorted(self._SUPPORTED_CONN_TYPES))}"
            )

        sys_config = self._resolve_system(system_name)
        resolved_name = system_name or self._config.default_system

        cache_key = (resolved_name, conn_type)
        entry = self._cache.get(cache_key)

        if entry is not None:
            age = time.monotonic() - entry.created_at
            if age >= self._cache_ttl:
                del self._cache[cache_key]
                entry = None

        if entry is None:
            if conn_type == 'adt':
                conn = self._create_adt_connection(sys_config)
            else:
                conn = self._create_gcts_connection(sys_config)
            entry = _CacheEntry(connection=conn, created_at=time.monotonic())
            self._cache[cache_key] = entry

        return entry.connection
