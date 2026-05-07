"""
Actionable error message formatting for mcp-sapcli.

Each formatter produces a message with:
- What happened (brief description)
- Why (likely cause)
- What to do (concrete action)
"""


def format_auth_error(
    auth_type: str,
    system_name: str,
    host: str,
    original_error: Exception,
    is_retry: bool = False,
) -> str:
    """Format an authentication failure with context-aware guidance.

    Args:
        auth_type: 'cookie' or 'basic'.
        system_name: The configured system name (e.g. 'DEV').
        host: The SAP host.
        original_error: The original exception.
        is_retry: Whether this is after a retry attempt.
    """
    header = f"Authentication failed for system '{system_name}' ({host})"
    if is_retry:
        header += " after retry"

    if auth_type == 'cookie':
        cause = "The SSO cookie has likely expired."
        action = (
            "Refresh the SSO cookie and restart the MCP server. "
            "If using $ENV_VAR in config, ensure the variable contains a fresh cookie value."
        )
    else:
        cause = "Invalid username or password, or the account is locked."
        action = (
            "Verify the 'user' and 'password' in your config file "
            "or the referenced environment variables. "
            "Check that the account is not locked in the SAP system."
        )

    return f"{header}.\nCause: {cause}\nAction: {action}"


def format_connection_error(
    host: str,
    port: int,
    ssl: bool,
    original_error: Exception,
    service_type: str = 'ADT',
) -> list[str]:
    """Format a connection failure with actionable guidance.

    Args:
        host: Target hostname.
        port: Target port.
        ssl: Whether SSL/TLS was used.
        original_error: The original exception.
        service_type: 'ADT' or 'gCTS'.

    Returns:
        List of log messages for OperationResult.LogMessages.
    """
    header = f"Could not connect to {service_type} on {host}:{port}."

    ssl_hint = (
        "SSL is enabled — verify the server supports HTTPS on this port"
        if ssl
        else "SSL is disabled — the server may require HTTPS"
    )

    guidance = (
        f"Likely causes: host unreachable (check VPN/network), "
        f"wrong port, or {ssl_hint.lower()}."
    )

    action = f"Action: verify the host is reachable and port {port} is correct."

    return [f"{header} {guidance} {action}", str(original_error)]


def format_command_error(tool_name: str, original_error: Exception) -> str:
    """Format a command execution error with tool context.

    Args:
        tool_name: The MCP tool name that failed.
        original_error: The original SAPCliError.
    """
    return f"Tool '{tool_name}' failed: {original_error}"


def format_startup_error(error: Exception) -> str:
    """Format a startup failure into a user-friendly message.

    Args:
        error: The exception that caused the startup failure.

    Returns:
        Formatted error message suitable for stderr output.
    """
    # Import here to avoid circular dependency (ConfigError is in config.py)
    from sapclimcp.config import ConfigError

    if isinstance(error, ConfigError):
        return (
            f"Server startup failed: configuration error.\n"
            f"{error}\n"
            f"Action: check your config file path and contents."
        )

    if isinstance(error, ImportError):
        return (
            f"Server startup failed: missing dependency.\n"
            f"{error}\n"
            f"Action: ensure all dependencies are installed "
            f"(pip install -e . or uv pip install -e .)."
        )

    return (
        f"Server startup failed: unexpected error.\n"
        f"{type(error).__name__}: {error}\n"
        f"Action: this is likely a bug — please report it."
    )
