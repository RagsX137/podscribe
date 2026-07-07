"""Agent loop: GodSession manages conversation history, Ollama function calling, tool dispatch."""
from __future__ import annotations

import json
import shlex
from typing import Any, Callable, Optional

from . import agent_tools
from . import fs_tools
from .config import load_god_model
from .llm import chat_stream

SYSTEM_PROMPT = """You are the Podscribe assistant — a tool-calling agent for meeting transcription and management.

You have access to the following tools:
{TOOL_DESCRIPTIONS}

Guidelines:
- Be transparent: explain your reasoning before calling tools
- For recording: tell the user you're starting, call start_recording, explain they can type "stop" or "/stop" when done
- Call tools one at a time. Don't parallelize.
- If a tool returns an error, report it clearly and offer alternatives
- Summarize results concisely
- Use list_pods first to discover which pods exist before taking actions
"""


def _build_tool_defs() -> list[dict]:
    """Build JSON schema for Ollama /api/chat tools parameter."""
    return [
        {
            "type": "function",
            "function": {
                "name": "list_pods",
                "description": "List all existing pod names",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "pod_info",
                "description": "Get metadata and stats for a pod",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Pod name"}
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "init_pod_tool",
                "description": "Create a new pod",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Pod name (kebab-case)"},
                        "display_name": {"type": "string", "description": "Human-readable name"},
                        "role": {"type": "string", "description": "Role"},
                        "cadence": {"type": "string", "description": "Meeting cadence"},
                        "notes": {"type": "string", "description": "Private notes"},
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_meetings_tool",
                "description": "List meetings in a pod, optionally filtered",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                        "since": {"type": "string", "description": "Filter: 7d, 24h, or YYYY-MM-DD"},
                        "meeting_type": {"type": "string", "description": "Meeting type filter"},
                        "recent": {"type": "integer", "description": "Limit to N most recent"},
                    },
                    "required": ["pod_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "show_meeting",
                "description": "Get the raw transcript text for a meeting",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                        "meeting_id": {"type": "string", "description": "Meeting ID or 'latest'"},
                    },
                    "required": ["pod_name", "meeting_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_kt_tool",
                "description": "List KT (knowledge-transfer) sessions in a pod",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                    },
                    "required": ["pod_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "show_kt",
                "description": "Get the raw transcript text for a KT session",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                        "session_id": {"type": "string", "description": "KT session ID or 'latest'"},
                    },
                    "required": ["pod_name", "session_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_recording",
                "description": "Start a background recording session",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                        "model": {"type": "string", "description": "Whisper model"},
                        "backend": {
                            "type": "string",
                            "description": "ASR backend (default: auto — picks the best backend for the host)",
                            "enum": ["auto", "whisper-mlx", "whisper-faster", "parakeet-mlx", "parakeet-nemo"],
                        },
                        "vad": {"type": "integer", "description": "VAD aggressiveness 0-3"},
                        "meeting_type": {"type": "string", "description": "Meeting type"},
                    },
                    "required": ["pod_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "stop_recording",
                "description": "Stop the active recording and finalize the meeting",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_recording_status",
                "description": "Get current recording status (for TUI polling)",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "enhance_meeting",
                "description": "Run LLM enhance on a meeting transcript",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                        "meeting_id": {"type": "string", "description": "Meeting ID or 'latest'"},
                    },
                    "required": ["pod_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consolidate_meeting",
                "description": "Extract structured fields from enhanced summary and update CSV",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                        "meeting_id": {"type": "string", "description": "Meeting ID or 'latest'"},
                        "no_log": {"type": "boolean", "description": "Skip CSV update"},
                    },
                    "required": ["pod_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_transcripts",
                "description": "Full-text search across transcripts",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "pod": {"type": "string", "description": "Limit to one pod"},
                        "since": {"type": "string", "description": "Date filter"},
                        "meeting_type": {"type": "string", "description": "Type filter"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "glossary_list",
                "description": "List glossary entries for a pod",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                    },
                    "required": ["pod_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "glossary_add",
                "description": "Add a glossary entry for a pod",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                        "term": {"type": "string", "description": "Term to add"},
                        "category": {"type": "string", "description": "Category"},
                    },
                    "required": ["pod_name", "term"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "glossary_remove",
                "description": "Remove a glossary entry from a pod",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                        "term": {"type": "string", "description": "Term to remove"},
                    },
                    "required": ["pod_name", "term"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "export_data",
                "description": "Export all pod data to a tarball",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "out_path": {"type": "string", "description": "Output path (optional)"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "List files and directories under a path in the project",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path relative to project root (default '.')"},
                        "recursive": {"type": "boolean", "description": "Recurse into subdirectories"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_tool",
                "description": "Read a file in the project, optionally between start_line and end_line (1-based)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path relative to project root"},
                        "start_line": {"type": "integer", "description": "First line to return (1-based, inclusive)"},
                        "end_line": {"type": "integer", "description": "Last line to return (1-based, inclusive)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_fs",
                "description": "Fixed-string search across project files; returns [{file, line, text}]",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search string (fixed, not regex)"},
                        "path": {"type": "string", "description": "Root path to search (default '.')"},
                        "include_glob": {"type": "string", "description": "Glob filter, e.g. '*.py' or '*.md'"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_symbol",
                "description": "Find Python def/class declarations by name; returns [{file, line, kind, name}]",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Symbol name to find"},
                        "path": {"type": "string", "description": "Root path to search (default '.')"},
                    },
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_references",
                "description": "Find all occurrences of an identifier across project files; returns [{file, line, text}]",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Identifier to find"},
                        "path": {"type": "string", "description": "Root path to search (default '.')"},
                    },
                    "required": ["name"],
                },
            },
        },
    ]


def _build_tool_descriptions() -> str:
    lines = []
    for t in _build_tool_defs():
        fn = t["function"]
        params = fn.get("parameters", {}).get("properties", {})
        args_str = ", ".join(
            f"{k}: {v.get('description', k)}"
            for k, v in params.items()
        )
        lines.append(f"- {fn['name']}({args_str}): {fn['description']}")
    return "\n".join(lines)


def _resolve_model(cli_model: Optional[str] = None) -> Optional[str]:
    """Resolve the Ollama model tag for god mode.

    Priority:
    1. --model CLI flag
    2. podscribe.yaml → god.model
    3. podscribe.yaml → llm.model
    4. None (caller should surface a "configure a model" error)
    """
    if cli_model:
        return cli_model
    return load_god_model()


def _format_tool_result(name: str, result: Any) -> str:
    """Format a tool result into a plain string for Ollama tool-role messages."""
    if isinstance(result, str):
        text = result
    elif isinstance(result, list):
        text = "\n".join(str(item) for item in result)
    elif isinstance(result, dict) and "error" in result:
        text = f"Error: {result['error']}"
    else:
        text = json.dumps(result, indent=2, default=str)
    return agent_tools._truncate(text)


TOOL_REGISTRY: dict[str, Callable] = {
    "list_pods": agent_tools.list_pods,
    "pod_info": agent_tools.pod_info,
    "init_pod_tool": agent_tools.init_pod_tool,
    "list_meetings_tool": agent_tools.list_meetings_tool,
    "show_meeting": agent_tools.show_meeting,
    "list_kt_tool": agent_tools.list_kt_tool,
    "show_kt": agent_tools.show_kt,
    "start_recording": agent_tools.start_recording,
    "stop_recording": agent_tools.stop_recording,
    "get_recording_status": agent_tools.get_recording_status,
    "enhance_meeting": agent_tools.enhance_meeting,
    "consolidate_meeting": agent_tools.consolidate_meeting,
    "search_transcripts": agent_tools.search_transcripts,
    "glossary_list": agent_tools.glossary_list,
    "glossary_add": agent_tools.glossary_add,
    "glossary_remove": agent_tools.glossary_remove,
    "export_data": agent_tools.export_data,
    "list_directory":   fs_tools.list_directory,
    "read_file_tool":   fs_tools.read_file_tool,
    "search_fs":        fs_tools.search_fs,
    "find_symbol":      fs_tools.find_symbol,
    "find_references":  fs_tools.find_references,
}


class GodSession:
    """Agent loop: conversation history, Ollama function calling, tool dispatch."""

    def __init__(self, model: Optional[str] = None):
        resolved = _resolve_model(model)
        if not resolved:
            raise ValueError(
                "No LLM model configured for god mode.\n"
                "Set one with: podscribe config god set <model>\n"
                "  e.g. podscribe config god set qwen3.6:35b-mlx\n"
                "Or set a shared model: podscribe config llm set <model> '<template>'"
            )
        self.model = resolved
        from .providers.registry import build_provider
        from .config import load_project_config
        cfg = load_project_config()
        # Start from the shared llm config and overlay god-specific keys, so a
        # bare `god.model` inherits the project provider/base_url/api_key_env
        # instead of silently reverting to localhost Ollama.
        llm_cfg = {**(cfg.get("llm") or {}), **(cfg.get("god") or {})}
        llm_cfg["model"] = resolved
        self.provider = build_provider(llm_cfg, model=resolved)
        self.tool_defs = _build_tool_defs()
        self.registry = TOOL_REGISTRY
        self._build_system_message()
        self.messages: list = [self._system_message]

    def _build_system_message(self):
        desc = _build_tool_descriptions()
        text = SYSTEM_PROMPT.replace("{TOOL_DESCRIPTIONS}", desc)
        self._system_message = {"role": "system", "content": text}

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_system_context(self, text: str) -> None:
        """Add a system-originated message (e.g. slash command result)."""
        self.messages.append({"role": "system", "content": text})

    def run_prompt(self, text: str, *,
                   on_token: Callable[[str], None] = lambda t: None,
                   on_tool_call: Callable[[str, str], None] = lambda n, a: None,
                   on_result: Callable[[str], None] = lambda r: None,
                   ) -> Optional[str]:
        """Single-turn execution for one-shot mode. Returns the final response or None."""
        self.add_user_message(text)
        return self._step(on_token=on_token, on_tool_call=on_tool_call, on_result=on_result)

    def _step(self, *,
              on_token: Callable[[str], None] = lambda t: None,
              on_tool_call: Callable[[str, str], None] = lambda n, a: None,
              on_result: Callable[[str], None] = lambda r: None,
              ) -> Optional[str]:
        """One LLM call → tool call → result → loop until response. Returns final text or None."""
        max_turns = 10
        for turn in range(max_turns):
            accumulated_text = chat_stream(
                self.model,
                self.messages,
                tools=self.tool_defs,
                provider=self.provider,
                on_token=on_token,
                on_message=lambda msg: self._handle_message(msg, on_tool_call, on_result),
            )

            if accumulated_text is None:
                return None

            # Check if the most recent assistant message has tool_calls
            last_assistant = None
            for m in reversed(self.messages):
                if m.get("role") == "assistant":
                    last_assistant = m
                    break
            if last_assistant and last_assistant.get("tool_calls"):
                # Loop back — tool results are already in messages
                continue

            # No tool_calls → this is a final response
            return accumulated_text

        return "Agent reached max turns without a final response."

    def _handle_message(self, msg: dict,
                        on_tool_call: Callable[[str, str], None],
                        on_result: Callable[[str], None]) -> None:
        """Process an assistant message: append to history, dispatch tool calls."""
        self.messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return

        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}

            on_tool_call(name, args_raw)

            tool_fn = self.registry.get(name)
            if tool_fn is None:
                result = {"error": f"Unknown tool: {name}"}
            else:
                try:
                    result = tool_fn(**args)
                except Exception as e:
                    result = {"error": str(e)}

            result_text = _format_tool_result(name, result)
            self.messages.append({
                "role": "tool",
                "name": name,
                "content": result_text,
            })
            on_result(result_text)

    def interactive_repl(self, *,
                         on_token: Callable[[str], None] = lambda t: None,
                         on_tool_call: Callable[[str, str], None] = lambda n, a: None,
                         on_result: Callable[[str], None] = lambda r: None,
                         ) -> None:
        """Not implemented in agent.py — handled by god_view in tui.py.
        This method is here for programmatic use (e.g. tests).
        """
        raise NotImplementedError("Use god_view in tui.py for interactive REPL.")
