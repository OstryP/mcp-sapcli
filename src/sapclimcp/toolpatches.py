"""
Generic tool patching mechanism for sapcli MCP tools.

Patches modify ArgParserTool instances in-place so that
SapcliCommandTool sees an already-adapted tool and needs
no patching awareness at all.
"""

import os
import tempfile
from abc import ABC, abstractmethod
from types import SimpleNamespace
from collections.abc import Sequence
from typing import Any, Optional


class ToolPatch(ABC):
    """Abstract base class for tool patches.

    A patch modifies an ArgParserTool in-place: its input schema
    and its cmdfn. After apply(), the tool looks like it was always
    defined with the patched schema and the wrapped command function.
    """

    @abstractmethod
    def applies_to(self, tool_name: str, tool: Any) -> bool:
        """Check whether this patch should be applied to the given tool.

        Args:
            tool_name: The tool's registered name.
            tool: The ArgParserTool instance.

        Returns:
            True if this patch applies.
        """

    @abstractmethod
    def apply(self, tool: Any) -> None:
        """Modify the ArgParserTool in-place: schema and cmdfn.

        Args:
            tool: The ArgParserTool instance to patch.
        """


class SourceDataPatch(ToolPatch):
    """Replace file-based ``source`` parameter with inline ``source_data``.

    sapcli write commands expect ``source`` as a list of file paths.
    MCP clients cannot provide file paths, so this patch:
    - Replaces ``source`` with ``source_data`` (a string) in the tool schema
    - Wraps cmdfn so that at invocation time source_data is written to
      a tempfile, ``source=[tmppath]`` is set on args, and the tempfile
      is cleaned up in a finally block.
    """

    def applies_to(self, tool_name: str, tool: Any) -> bool:
        props = tool.input_schema.properties
        source_spec = props.get('source')
        return source_spec is not None and source_spec.get('type') == 'array'

    def apply(self, tool: Any) -> None:
        schema = tool.input_schema

        # Patch schema: remove source, add source_data
        schema.properties.pop('source', None)
        if 'source' in schema.required:
            schema.required.remove('source')

        schema.properties['source_data'] = {
            'type': 'string',
            'description': 'Inline source code content',
        }
        if 'source_data' not in schema.required:
            schema.required.append('source_data')

        # Wrap cmdfn: source_data -> tempfile -> source=[tmppath] -> cleanup
        original_cmdfn = tool.cmdfn

        def wrapped_cmdfn(conn: Any, args: SimpleNamespace) -> None:
            source_data = getattr(args, 'source_data', None)
            if source_data is None:
                original_cmdfn(conn, args)
                return

            fd, tmppath = tempfile.mkstemp(suffix='.abap')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as fobj:
                    fobj.write(source_data)
            except Exception:
                os.unlink(tmppath)
                raise

            args.source = [tmppath]
            try:
                original_cmdfn(conn, args)
            finally:
                try:
                    os.unlink(tmppath)
                except OSError:
                    pass

        tool.cmdfn = wrapped_cmdfn


class ConnectionPatch(ToolPatch):
    """Strip connection parameters from tool schemas and add a system selector.

    When the server manages connections server-side, the LLM should not
    see or provide ``ashost``, ``client``, ``user``, ``password``, etc.
    This patch:

    - Removes all connection parameters from the tool's input schema
    - Adds an optional ``system`` parameter when multiple systems are
      configured (or a single system with a default)
    """

    CONNECTION_PARAMS = frozenset({
        'ashost', 'port', 'client', 'user', 'password',
        'ssl', 'verify', 'sysnr',
    })

    def __init__(
        self,
        system_names: list[str],
        default_system: Optional[str] = None,
    ) -> None:
        self._system_names = system_names
        self._default_system = default_system

    def applies_to(self, tool_name: str, tool: Any) -> bool:
        return bool(
            self.CONNECTION_PARAMS & set(tool.input_schema.properties.keys())
        )

    def apply(self, tool: Any) -> None:
        schema = tool.input_schema

        for param in self.CONNECTION_PARAMS:
            schema.properties.pop(param, None)
            if param in schema.required:
                schema.required.remove(param)

        if len(self._system_names) > 1:
            desc = f'Target SAP system. Available: {", ".join(self._system_names)}'
            if self._default_system:
                desc += f'. Default: {self._default_system}'
            schema.properties['system'] = {
                'type': 'string',
                'description': desc,
            }
            if not self._default_system:
                schema.required.append('system')
        elif len(self._system_names) == 1:
            schema.properties['system'] = {
                'type': 'string',
                'description': f'Target SAP system (default: {self._system_names[0]})',
                'default': self._system_names[0],
            }


def apply_patches(
    tool_name: str,
    tool: Any,
    patch_registry: Sequence[ToolPatch],
) -> None:
    """Find and apply applicable patches to a tool in-place.

    Args:
        tool_name: The tool name.
        tool: The ArgParserTool instance to patch.
        patch_registry: List of available patches.
    """
    for patch in patch_registry:
        if patch.applies_to(tool_name, tool):
            patch.apply(tool)
