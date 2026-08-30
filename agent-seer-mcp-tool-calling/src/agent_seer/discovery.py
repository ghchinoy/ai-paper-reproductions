"""Dynamic MCP Server Discovery, stdio Handshake & Capability Registry Loader."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from .models import CapabilityMatrix, ServerSpec, ToolDefinition

logger = logging.getLogger("agent_seer.discovery")


def _read_json_line(pipe, timeout_sec: float = 5.0, proc_name: str = "mcp") -> dict:
    """Reads a single JSON line from pipe with timeout and blank line skipping."""
    result = [None]
    exception = [None]
    event = threading.Event()

    def reader():
        try:
            while True:
                line = pipe.readline()
                if line == "":
                    exception[0] = EOFError(f"Subprocess '{proc_name}' closed standard output unexpectedly")
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    result[0] = json.loads(stripped)
                except Exception:
                    exception[0] = ValueError(f"Malformed JSON from subprocess '{proc_name}': {stripped}")
                break
        except Exception as e:
            exception[0] = e
        finally:
            event.set()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout_sec)

    if not event.is_set():
        raise TimeoutError(f"Timed out after {timeout_sec}s waiting for output from '{proc_name}'")

    if exception[0] is not None:
        raise exception[0]

    return result[0]


class McpDiscovery:
    """Discovers tools via MCP JSON-RPC 2.0 stdio handshake or static filesystem registries."""

    @staticmethod
    def discover_from_stdio(
        command_or_args: Union[str, List[str]],
        timeout_sec: float = 10.0,
        env: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Executes initialize -> notifications/initialized -> tools/list over stdio."""
        if isinstance(command_or_args, str):
            cmd = command_or_args.split()
            cmd_str = command_or_args
        else:
            cmd = list(command_or_args)
            cmd_str = " ".join(command_or_args)

        if not cmd:
            raise ValueError("Command cannot be empty")

        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=merged_env,
        )

        try:
            # 1. initialize
            init_req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "agent-seer", "version": "1.0.0"},
                },
            }
            proc.stdin.write(json.dumps(init_req) + "\n")
            proc.stdin.flush()

            init_resp = _read_json_line(proc.stdout, timeout_sec=timeout_sec, proc_name=cmd_str)
            if init_resp and "error" in init_resp:
                err = init_resp["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"MCP initialize error: {msg}")

            # 2. notifications/initialized
            init_notif = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
            proc.stdin.write(json.dumps(init_notif) + "\n")
            proc.stdin.flush()

            # 3. tools/list
            tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            proc.stdin.write(json.dumps(tools_req) + "\n")
            proc.stdin.flush()

            tools_resp = _read_json_line(proc.stdout, timeout_sec=timeout_sec, proc_name=cmd_str)
            if tools_resp and "error" in tools_resp:
                err = tools_resp["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"MCP tools/list error: {msg}")

            if tools_resp and isinstance(tools_resp.get("result"), dict):
                raw_tools = tools_resp["result"].get("tools")
                if isinstance(raw_tools, list):
                    return raw_tools

            return []
        finally:
            try:
                proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                proc.kill()


# Top-level functional aliases
discover_from_stdio = McpDiscovery.discover_from_stdio
discover_tools_stdio = McpDiscovery.discover_from_stdio


def load_capabilities(path_or_dict: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Loads capability matrix from JSON file or dictionary."""
    if isinstance(path_or_dict, dict):
        return path_or_dict
    if isinstance(path_or_dict, str) and os.path.exists(path_or_dict):
        with open(path_or_dict) as f:
            return json.load(f)
    return {}


def load_server_directory(server_dir: str) -> ServerSpec:
    """Loads ServerSpec from directory containing tools_list.json / tools.json and capabilities.json."""
    tools: List[ToolDefinition] = []
    caps: Dict[str, Any] = {}
    name = os.path.basename(os.path.normpath(server_dir))

    tpath = os.path.join(server_dir, "tools_list.json")
    if not os.path.exists(tpath):
        tpath = os.path.join(server_dir, "tools.json")

    if os.path.exists(tpath):
        with open(tpath) as f:
            data = json.load(f)
            raw_tools = data.get("tools", []) if isinstance(data, dict) else data
            if raw_tools is not None:
                for rt in raw_tools:
                    if isinstance(rt, dict):
                        tools.append(ToolDefinition.from_mcp_tool(rt))

    cpath = os.path.join(server_dir, "capabilities.json")
    if os.path.exists(cpath):
        with open(cpath) as f:
            data = json.load(f)
            if isinstance(data, dict):
                caps = data

    return ServerSpec(
        server_name=name,
        name=name,
        tools=tools,
        capabilities=caps,
        source_dir=server_dir,
    )


def load_registry(servers_dir: str) -> Dict[str, ServerSpec]:
    """Loads all server specifications from a root servers directory."""
    registry = {}
    if not os.path.exists(servers_dir):
        return registry

    for entry in os.listdir(servers_dir):
        full_path = os.path.join(servers_dir, entry)
        if os.path.isdir(full_path):
            spec = load_server_directory(full_path)
            registry[entry] = spec
    return registry


def merge_capabilities(
    tools: Union[List[Dict[str, Any]], List[ToolDefinition]],
    capabilities: Union[Dict[str, Any], CapabilityMatrix, None],
) -> str:
    """Merges tools and capability matrix into an enriched prompt specification block."""
    raw_tools = [t.to_dict() if hasattr(t, "to_dict") else t for t in tools]
    specs_json = json.dumps(raw_tools, indent=2)

    if not capabilities:
        return specs_json

    caps_dict = capabilities.to_dict() if hasattr(capabilities, "to_dict") else capabilities
    return (
        specs_json
        + "\n\nCRITICAL BACKEND MODEL CAPABILITY MATRIX (MUST ENFORCE):\n"
        + json.dumps(caps_dict, indent=2)
    )


def load_tools_and_capabilities(
    server_path_or_json: str, capabilities_path: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Loads tools list and capabilities dictionary from paths, directories, or stdio commands."""
    tools: List[Dict[str, Any]] = []
    caps: Dict[str, Any] = {}

    if not os.path.exists(server_path_or_json):
        tools = discover_from_stdio(server_path_or_json)
    elif os.path.isdir(server_path_or_json):
        spec = load_server_directory(server_path_or_json)
        tools = [t.to_dict() for t in spec.tools]
        caps = spec.capabilities
    elif os.path.isfile(server_path_or_json):
        if server_path_or_json.endswith(".json"):
            with open(server_path_or_json) as f:
                data = json.load(f)
                tools = data.get("tools", []) if isinstance(data, dict) else data
        elif os.access(server_path_or_json, os.X_OK):
            tools = discover_from_stdio([server_path_or_json])

    if capabilities_path and os.path.exists(capabilities_path):
        caps = load_capabilities(capabilities_path)

    return tools, caps
