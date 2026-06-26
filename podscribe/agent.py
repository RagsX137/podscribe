"""Agent loop: GodSession manages conversation history, Ollama function calling, tool dispatch."""
from __future__ import annotations

import json
import shlex
from typing import Any, Callable, Optional

from . import agent_tools
from .config import load_project_config
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
                "name": "start_recording",
                "description": "Start a background recording session",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pod_name": {"type": "string", "description": "Pod name"},
                        "model": {"type": "string", "description": "Whisper model"},
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


def _resolve_model(cli_model: Optional[str] = None) -> str:
    if cli_model:
        return cli_model
    cfg = load_project_config().get("llm", {})
    return cfg.get("model") or "qwen3.6:27b-mlx"


def _format_tool_result(name: str, result: Any) -> str:
    """Format a tool result into a string for the conversation."""
    text = json.dumps(result, indent=2, default=str) if not isinstance(result, str) else result
    return agent_tools._truncate(text)


TOOL_REGISTRY: dict[str, Callable] = {
    "list_pods": agent_tools.list_pods,
    "pod_info": agent_tools.pod_info,
    "init_pod_tool": agent_tools.init_pod_tool,
    "list_meetings_tool": agent_tools.list_meetings_tool,
    "show_meeting": agent_tools.show_meeting,
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
}


class GodSession:
    """Agent loop: conversation history, Ollama function calling, tool dispatch."""

    def __init__(self, model: Optional[str] = None):
        self.model = _resolve_model(model)
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
                on_token=on_token,
                on_message=lambda msg: self._handle_message(msg, on_tool_call, on_result),
            )

            if accumulated_text is None:
                return None

            # Check if the last assistant message has tool_calls
            last = self.messages[-1] if self.messages else None
            if last and last.get("role") == "assistant" and last.get("tool_calls"):
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
