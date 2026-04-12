"""Deterministic post-processing for graph edges produced by graphify."""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

MONITOR_TOOL_NAME = "monitor_availability"
MCP_CHAT_AGENT_LABEL = "MCPChatAgent"
MCP_SERVER_MODULE = "wiesn_agent.mcp_server"

_MODULE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_PATH = _MODULE_ROOT / "src" / "wiesn_agent" / "api.py"
DEFAULT_CHAT_AGENT_PATH = _MODULE_ROOT / "src" / "wiesn_agent" / "chat_agent.py"
DEFAULT_MCP_SERVER_PATH = _MODULE_ROOT / "src" / "wiesn_agent" / "mcp_server.py"


@dataclass(frozen=True)
class WiringEvidence:
    """AST evidence that MCP chat wiring to monitor_availability is explicit."""

    scanner_tools_line: int | None
    filter_tools_line: int | None
    scanner_agent_tools_line: int | None
    mcp_stdio_line: int | None
    monitor_tool_line: int | None

    @property
    def is_deterministic(self) -> bool:
        return all(
            value is not None
            for value in (
                self.scanner_tools_line,
                self.filter_tools_line,
                self.scanner_agent_tools_line,
                self.mcp_stdio_line,
                self.monitor_tool_line,
            )
        )


@dataclass(frozen=True)
class ApiChatWiringEvidence:
    """AST evidence that API chat handler calls the chat agent entrypoint."""

    chat_import_line: int | None
    chat_call_line: int | None

    @property
    def is_deterministic(self) -> bool:
        return all(value is not None for value in (self.chat_import_line, self.chat_call_line))


@dataclass(frozen=True)
class TriageRoutingEvidence:
    """AST evidence that triage routes to scanner/form/notifier executors."""

    triage_constructor_line: int | None
    scanner_edge_line: int | None
    form_edge_line: int | None
    notifier_edge_line: int | None

    @property
    def is_deterministic(self) -> bool:
        return all(
            value is not None
            for value in (
                self.triage_constructor_line,
                self.scanner_edge_line,
                self.form_edge_line,
                self.notifier_edge_line,
            )
        )


@dataclass(frozen=True)
class MonitorScannerCallEvidence:
    """AST evidence that monitor_availability calls scanner functions."""

    scan_portal_availability_line: int | None
    compare_snapshots_line: int | None
    filter_relevant_changes_line: int | None
    deep_scan_date_line: int | None

    @property
    def is_deterministic(self) -> bool:
        return all(
            value is not None
            for value in (
                self.scan_portal_availability_line,
                self.compare_snapshots_line,
                self.filter_relevant_changes_line,
                self.deep_scan_date_line,
            )
        )


@dataclass(frozen=True)
class PostpassResult:
    """Result metadata after applying the post-pass."""

    graph_path: Path
    output_path: Path
    source_node_id: str
    target_node_id: str
    removed_edges: int
    evidence: WiringEvidence


def _load_module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _extract_string_literals(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        values: set[str] = set()
        for item in node.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                values.add(item.value)
        return values
    return set()


def _find_scanner_tools_line(module_ast: ast.Module) -> int | None:
    for node in module_ast.body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            if any(t.id == "SCANNER_TOOLS" for t in targets):
                if MONITOR_TOOL_NAME in _extract_string_literals(node.value):
                    return node.lineno
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "SCANNER_TOOLS":
                if node.value is not None and MONITOR_TOOL_NAME in _extract_string_literals(node.value):
                    return node.lineno
    return None


def _find_class(module_ast: ast.Module, class_name: str) -> ast.ClassDef | None:
    for node in module_ast.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _find_function(
    module_ast: ast.Module, function_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in module_ast.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    return None


def _get_method(class_node: ast.ClassDef, method_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in class_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
            return node
    return None


def _get_call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _get_str_keyword(call: ast.Call, keyword_name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg != keyword_name:
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
    return None


def _is_filter_tools_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != "_filter_tools":
        return False
    if not isinstance(node.func.value, ast.Name) or node.func.value.id != "self":
        return False
    if not node.args:
        return False
    first_arg = node.args[0]
    return isinstance(first_arg, ast.Name) and first_arg.id == "SCANNER_TOOLS"


def _find_filter_tools_line(method_node: ast.FunctionDef | ast.AsyncFunctionDef | None) -> int | None:
    if method_node is None:
        return None
    for node in ast.walk(method_node):
        if not isinstance(node, ast.Compare):
            continue
        if len(node.ops) != 1 or not isinstance(node.ops[0], ast.In):
            continue
        if len(node.comparators) != 1:
            continue
        comparator = node.comparators[0]
        if not isinstance(comparator, ast.Name) or comparator.id != "tool_names":
            continue
        if isinstance(node.left, ast.Attribute) and node.left.attr == "name":
            return node.lineno
    return None


def _find_scanner_agent_tools_line(method_node: ast.FunctionDef | ast.AsyncFunctionDef | None) -> int | None:
    if method_node is None:
        return None
    for node in ast.walk(method_node):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "Agent":
            continue
        for keyword in node.keywords:
            if keyword.arg == "tools" and _is_filter_tools_call(keyword.value):
                return keyword.value.lineno
    return None


def _contains_mcp_module_args(args_node: ast.AST) -> bool:
    if not isinstance(args_node, (ast.List, ast.Tuple)):
        return False
    values: list[str] = []
    for item in args_node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return False
        values.append(item.value)
    for index in range(len(values) - 1):
        if values[index] == "-m" and values[index + 1] == MCP_SERVER_MODULE:
            return True
    return False


def _find_mcp_stdio_line(method_node: ast.FunctionDef | ast.AsyncFunctionDef | None) -> int | None:
    if method_node is None:
        return None
    for node in ast.walk(method_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            is_mcp_stdio = func.id == "MCPStdioTool"
        elif isinstance(func, ast.Attribute):
            is_mcp_stdio = func.attr == "MCPStdioTool"
        else:
            is_mcp_stdio = False
        if not is_mcp_stdio:
            continue
        for keyword in node.keywords:
            if keyword.arg == "args" and _contains_mcp_module_args(keyword.value):
                return node.lineno
    return None


def _is_mcp_tool_decorator(node: ast.AST) -> bool:
    candidate = node.func if isinstance(node, ast.Call) else node
    if not isinstance(candidate, ast.Attribute):
        return False
    if candidate.attr != "tool":
        return False
    return isinstance(candidate.value, ast.Name) and candidate.value.id == "mcp"


def _find_monitor_tool_line(module_ast: ast.Module) -> int | None:
    for node in module_ast.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == MONITOR_TOOL_NAME:
            if any(_is_mcp_tool_decorator(decorator) for decorator in node.decorator_list):
                return node.lineno
    return None


def detect_monitor_availability_wiring(chat_agent_path: Path, mcp_server_path: Path) -> WiringEvidence:
    """Detect deterministic MCP wiring for monitor_availability using AST checks."""
    chat_ast = _load_module_ast(chat_agent_path)
    mcp_ast = _load_module_ast(mcp_server_path)
    chat_class = _find_class(chat_ast, MCP_CHAT_AGENT_LABEL)

    filter_tools_method = _get_method(chat_class, "_filter_tools") if chat_class else None
    build_workflow_method = _get_method(chat_class, "_build_workflow") if chat_class else None
    connect_method = _get_method(chat_class, "connect") if chat_class else None

    return WiringEvidence(
        scanner_tools_line=_find_scanner_tools_line(chat_ast),
        filter_tools_line=_find_filter_tools_line(filter_tools_method),
        scanner_agent_tools_line=_find_scanner_agent_tools_line(build_workflow_method),
        mcp_stdio_line=_find_mcp_stdio_line(connect_method),
        monitor_tool_line=_find_monitor_tool_line(mcp_ast),
    )


def detect_api_chat_wiring(api_path: Path) -> ApiChatWiringEvidence:
    """Detect deterministic API chat handler call to chat_agent.chat()."""
    api_ast = _load_module_ast(api_path)
    post_chat_fn = _find_function(api_ast, "post_chat")
    if post_chat_fn is None:
        return ApiChatWiringEvidence(chat_import_line=None, chat_call_line=None)

    imported_chat_name: str | None = None
    chat_import_line: int | None = None
    for node in ast.walk(post_chat_fn):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "wiesn_agent.chat_agent":
            continue
        for imported in node.names:
            if imported.name != "chat":
                continue
            imported_chat_name = imported.asname or imported.name
            chat_import_line = node.lineno
            break
        if imported_chat_name is not None:
            break

    chat_call_line: int | None = None
    if imported_chat_name is not None:
        for node in ast.walk(post_chat_fn):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == imported_chat_name:
                chat_call_line = node.lineno
                break

    return ApiChatWiringEvidence(chat_import_line=chat_import_line, chat_call_line=chat_call_line)


def _collect_triage_edge_lines(
    method_node: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> tuple[int | None, int | None, int | None, int | None]:
    if method_node is None:
        return (None, None, None, None)

    triage_constructor_line: int | None = None
    triage_identifiers: set[str] = set()
    for node in ast.walk(method_node):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if _get_call_name(node.value) != "TriageExecutor":
            continue
        triage_constructor_line = node.lineno
        for target in node.targets:
            if isinstance(target, ast.Name):
                triage_identifiers.add(target.id)
    if not triage_identifiers:
        triage_identifiers.add("triage")

    scanner_edge_line: int | None = None
    form_edge_line: int | None = None
    notifier_edge_line: int | None = None
    for node in ast.walk(method_node):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_edge":
            continue
        if len(node.args) < 2:
            continue
        source = node.args[0]
        target = node.args[1]
        if not isinstance(source, ast.Name) or source.id not in triage_identifiers:
            continue
        if not isinstance(target, ast.Call) or _get_call_name(target) != "AgentExecutor":
            continue

        edge_id = _get_str_keyword(target, "id")
        if edge_id == "scanner" and scanner_edge_line is None:
            scanner_edge_line = node.lineno
        elif edge_id == "form-agent" and form_edge_line is None:
            form_edge_line = node.lineno
        elif edge_id == "notifier" and notifier_edge_line is None:
            notifier_edge_line = node.lineno

    return triage_constructor_line, scanner_edge_line, form_edge_line, notifier_edge_line


def detect_triage_routing_wiring(chat_agent_path: Path) -> TriageRoutingEvidence:
    """Detect deterministic triage routing edges in MCPChatAgent workflow."""
    chat_ast = _load_module_ast(chat_agent_path)
    chat_class = _find_class(chat_ast, MCP_CHAT_AGENT_LABEL)
    build_workflow_method = _get_method(chat_class, "_build_workflow") if chat_class else None
    triage_constructor_line, scanner_edge_line, form_edge_line, notifier_edge_line = (
        _collect_triage_edge_lines(build_workflow_method)
    )
    return TriageRoutingEvidence(
        triage_constructor_line=triage_constructor_line,
        scanner_edge_line=scanner_edge_line,
        form_edge_line=form_edge_line,
        notifier_edge_line=notifier_edge_line,
    )


def _find_first_call_line(
    method_node: ast.FunctionDef | ast.AsyncFunctionDef | None,
    function_name: str,
) -> int | None:
    if method_node is None:
        return None
    for node in ast.walk(method_node):
        if not isinstance(node, ast.Call):
            continue
        if _get_call_name(node) == function_name:
            return node.lineno
    return None


def detect_monitor_scanner_call_wiring(mcp_server_path: Path) -> MonitorScannerCallEvidence:
    """Detect deterministic scanner call chain inside monitor_availability."""
    mcp_ast = _load_module_ast(mcp_server_path)
    monitor_fn = _find_function(mcp_ast, MONITOR_TOOL_NAME)
    return MonitorScannerCallEvidence(
        scan_portal_availability_line=_find_first_call_line(monitor_fn, "scan_portal_availability"),
        compare_snapshots_line=_find_first_call_line(monitor_fn, "compare_snapshots"),
        filter_relevant_changes_line=_find_first_call_line(monitor_fn, "filter_relevant_changes"),
        deep_scan_date_line=_find_first_call_line(monitor_fn, "deep_scan_date"),
    )


def _score_chat_agent_node(node: dict[str, Any]) -> int:
    label = str(node.get("label", "")).strip()
    normalized_label = re.sub(r"[^a-z0-9]+", "", label.lower())
    node_id = str(node.get("id", "")).lower()
    source_file = str(node.get("source_file", "")).replace("/", "\\").lower()

    score = -100
    if label == MCP_CHAT_AGENT_LABEL:
        score = 200
    elif normalized_label == "mcpchatagent":
        score = 190
    elif "mcp chat agent" in label.lower():
        score = 180
    elif MCP_CHAT_AGENT_LABEL.lower() in label.lower():
        score = 150
    elif "mcpchatagent" in node_id:
        score = 140
    elif "mcp_chat_agent" in node_id:
        score = 140

    if source_file.endswith("src\\wiesn_agent\\chat_agent.py"):
        score += 20
    return score


def _score_monitor_node(node: dict[str, Any]) -> int:
    label = str(node.get("label", "")).strip()
    label_lower = label.lower()
    normalized_label = re.sub(r"[^a-z0-9]+", "", label_lower)
    node_id = str(node.get("id", "")).lower()
    source_file = str(node.get("source_file", "")).replace("/", "\\").lower()

    score = -100
    if label == "monitor_availability()":
        score = 220
    elif "mcp monitor availability tool" in label_lower:
        score = 210
    elif normalized_label == "monitoravailability":
        score = 200
    elif "monitor availability" in label_lower:
        score = 190
    elif label.startswith("monitor_availability("):
        score = 210
    elif label == MONITOR_TOOL_NAME:
        score = 190
    elif MONITOR_TOOL_NAME in label_lower:
        score = 150
    elif MONITOR_TOOL_NAME in node_id:
        score = 140

    if source_file.endswith("src\\wiesn_agent\\mcp_server.py"):
        score += 25
    if node_id.endswith("_monitor_availability"):
        score += 20
    if "rationale" in node_id or "rationale" in label_lower:
        score -= 100
    return score


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _score_api_chat_handler_node(node: dict[str, Any]) -> int:
    label = str(node.get("label", "")).strip()
    label_lower = label.lower()
    normalized_label = _normalize_text(label)
    node_id = str(node.get("id", "")).lower()
    normalized_id = _normalize_text(node_id)
    source_file = str(node.get("source_file", "")).replace("/", "\\").lower()

    score = -100
    if label == "API Chat Handler":
        score = 230
    elif normalized_label == "apichathandler":
        score = 220
    elif "api" in label_lower and "chat" in label_lower and "handler" in label_lower:
        score = 210
    elif node_id == "api_chat_handler":
        score = 205
    elif "api_chat_handler" in node_id:
        score = 200
    elif "post_chat" in node_id:
        score = 180
    elif "apichat" in normalized_id:
        score = 170

    if source_file.endswith("src\\wiesn_agent\\api.py"):
        score += 25
    if "rationale" in node_id or "rationale" in label_lower:
        score -= 120
    return score


def _score_chat_entrypoint_node(node: dict[str, Any]) -> int:
    label = str(node.get("label", "")).strip()
    label_lower = label.lower()
    normalized_label = _normalize_text(label)
    node_id = str(node.get("id", "")).lower()
    normalized_id = _normalize_text(node_id)
    source_file = str(node.get("source_file", "")).replace("/", "\\").lower()

    score = -100
    if label == "Chat Agent Entrypoint":
        score = 235
    elif normalized_label == "chatagententrypoint":
        score = 225
    elif "chat entrypoint" in label_lower:
        score = 210
    elif node_id == "chat_agent_chat_entrypoint":
        score = 220
    elif "chat_entrypoint" in node_id:
        score = 205
    elif normalized_id.endswith("chatentrypoint"):
        score = 195
    elif label.startswith("chat("):
        score = 175
    elif normalized_id in {"chatagentchatentrypoint", "chatagentchat"}:
        score = 165

    if "mcpchatagent" in normalized_label or "mcpchatagent" in normalized_id:
        score -= 150
    if source_file.endswith("src\\wiesn_agent\\chat_agent.py"):
        score += 20
    if "rationale" in node_id or "rationale" in label_lower:
        score -= 120
    return score


def _score_triage_executor_node(node: dict[str, Any]) -> int:
    label = str(node.get("label", "")).strip()
    label_lower = label.lower()
    normalized_label = _normalize_text(label)
    node_id = str(node.get("id", "")).lower()
    normalized_id = _normalize_text(node_id)
    source_file = str(node.get("source_file", "")).replace("/", "\\").lower()

    score = -100
    if label == "Triage Executor":
        score = 235
    elif normalized_label == "triageexecutor":
        score = 225
    elif "triage" in label_lower and "executor" in label_lower:
        score = 210
    elif node_id == "chat_agent_triage_executor":
        score = 220
    elif "triage_executor" in node_id:
        score = 200
    elif "triage" in normalized_id:
        score = 170

    if source_file.endswith("src\\wiesn_agent\\chat_agent.py"):
        score += 20
    if "rationale" in node_id or "rationale" in label_lower:
        score -= 120
    return score


def _score_triage_target_node(node: dict[str, Any], route_id: str) -> int:
    label = str(node.get("label", "")).strip()
    label_lower = label.lower()
    normalized_label = _normalize_text(label)
    node_id = str(node.get("id", "")).lower()
    normalized_id = _normalize_text(node_id)
    source_file = str(node.get("source_file", "")).replace("/", "\\").lower()
    source_is_chat_agent = source_file.endswith("src\\wiesn_agent\\chat_agent.py")

    route_normalized = _normalize_text(route_id)
    if route_id == "form-agent":
        keywords = {"formagent", "form"}
        exact_ids = {
            "formagent",
            "chatagentformagent",
            "chatagentformagentexecutor",
            "formagentexecutor",
            "formexecutor",
            "formagentagentexecutor",
            "formagentexecutornode",
        }
    elif route_id == "notifier":
        keywords = {"notifier", "notify"}
        exact_ids = {
            "notifier",
            "chatagentnotifier",
            "chatagentnotifierexecutor",
            "notifierexecutor",
            "notifieragentexecutor",
            "notifyexecutor",
            "notifyagentexecutor",
        }
    else:
        keywords = {"scanner", "scan"}
        exact_ids = {
            "scanner",
            "chatagentscanner",
            "chatagentscannerexecutor",
            "scannerexecutor",
            "scanneragentexecutor",
            "scanexecutor",
            "scanagentexecutor",
        }

    has_route = route_normalized in normalized_id or route_normalized in normalized_label
    if not has_route:
        has_route = any(keyword in normalized_id or keyword in normalized_label for keyword in keywords)

    has_executor_marker = "executor" in normalized_id or "executor" in normalized_label
    has_agent_marker = "agent" in normalized_id or "agent" in normalized_label

    score = -100
    if normalized_id in exact_ids:
        score = 245
    elif has_route and has_executor_marker:
        score = 225
    elif has_route and has_agent_marker:
        score = 205
    elif has_route and source_is_chat_agent:
        score = 180

    if source_is_chat_agent:
        score += 20
    elif source_file and has_route and not (has_executor_marker or has_agent_marker):
        score -= 140

    if "rationale" in node_id or "rationale" in label_lower:
        score -= 120
    return score


def _score_scanner_chain_target(node: dict[str, Any], function_name: str) -> int:
    label = str(node.get("label", "")).strip()
    label_lower = label.lower()
    normalized_label = _normalize_text(label)
    node_id = str(node.get("id", "")).lower()
    normalized_id = _normalize_text(node_id)
    source_file = str(node.get("source_file", "")).replace("/", "\\").lower()
    normalized_fn = _normalize_text(function_name)
    exact_id = f"scanner_{function_name}"

    alias_labels = {
        "scan_portal_availability": {"portalavailabilityscanner"},
        "compare_snapshots": {"snapshotcomparator"},
        "filter_relevant_changes": {"relevantchangefilter"},
        "deep_scan_date": {"datedeepscanner"},
    }.get(function_name, set())

    score = -100
    if node_id == exact_id:
        score = 245
    elif function_name in node_id:
        score = 230
    elif normalized_fn in normalized_id:
        score = 220
    elif normalized_fn in normalized_label:
        score = 215
    elif any(alias in normalized_label for alias in alias_labels):
        score = 205
    elif any(alias in normalized_id for alias in alias_labels):
        score = 195

    if source_file.endswith("src\\wiesn_agent\\scanner.py"):
        score += 20
    if "rationale" in node_id or "rationale" in label_lower:
        score -= 120
    return score


def _select_node_id(
    nodes: list[dict[str, Any]],
    scorer: Callable[[dict[str, Any]], int],
    node_role: str,
) -> str:
    best_id: str | None = None
    best_score = -1000
    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        score = scorer(node)
        if score > best_score:
            best_score = score
            best_id = node_id
    if best_id is None or best_score < 0:
        raise ValueError(f"Unable to resolve graph node for {node_role}.")
    return best_id


def _try_select_node_id(
    nodes: list[dict[str, Any]],
    scorer: Callable[[dict[str, Any]], int],
) -> str | None:
    best_id: str | None = None
    best_score = -1000
    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        score = scorer(node)
        if score > best_score:
            best_score = score
            best_id = node_id
    if best_id is None or best_score < 0:
        return None
    return best_id


def _edge_matches_pair(edge: dict[str, Any], source_id: str, target_id: str) -> bool:
    expected = {source_id, target_id}
    for src_key, tgt_key in (("source", "target"), ("_src", "_tgt")):
        src = edge.get(src_key)
        tgt = edge.get(tgt_key)
        if isinstance(src, str) and isinstance(tgt, str):
            if {src, tgt} == expected:
                return True
    return False


def _deterministic_call_edge(
    source_id: str,
    target_id: str,
    source_file: str,
    source_location: str | None,
    *,
    relation: str = "calls",
    confidence_score: float = 1.0,
    weight: float = 1.0,
) -> dict[str, Any]:
    edge = {
        "relation": relation,
        "confidence": "EXTRACTED",
        "confidence_score": confidence_score,
        "weight": weight,
        "_src": source_id,
        "_tgt": target_id,
        "source": source_id,
        "target": target_id,
        "source_file": source_file,
    }
    if source_location:
        edge["source_location"] = source_location
    return edge


def _as_windows_relative(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        relative = path.resolve()
    return str(relative).replace("/", "\\")


def _is_semantic_relation(relation: str) -> bool:
    relation_lower = relation.lower()
    return "semantic" in relation_lower or relation_lower in {"semantically_similar_to", "semantic_similarity"}


def _is_exact_edge(edge: dict[str, Any]) -> bool:
    relation = str(edge.get("relation", ""))
    confidence = str(edge.get("confidence", "")).upper()
    return confidence == "EXTRACTED" and not _is_semantic_relation(relation)


def _as_float(value: Any, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    return fallback


def _pick_preferred_exact_edge(
    exact_edges: list[dict[str, Any]],
    source_id: str,
    target_id: str,
    preferred_relation: str,
) -> dict[str, Any]:
    preferred_relation_lower = preferred_relation.lower()

    def _score(edge: dict[str, Any]) -> tuple[int, int, float]:
        relation = str(edge.get("relation", "")).lower()
        preferred = 1 if relation == preferred_relation_lower else 0
        directional = 1 if edge.get("source") == source_id and edge.get("target") == target_id else 0
        confidence_score = _as_float(edge.get("confidence_score"), 1.0)
        return (preferred, directional, confidence_score)

    return max(exact_edges, key=_score)


def _remove_pair_edges(
    graph_data: dict[str, Any],
    source_id: str,
    target_id: str,
) -> int:
    edge_keys = [key for key in ("links", "edges") if isinstance(graph_data.get(key), list)]
    removed_edges = 0
    for key in edge_keys:
        original_edges = graph_data[key]
        kept_edges: list[dict[str, Any]] = []
        for edge in original_edges:
            if isinstance(edge, dict) and _edge_matches_pair(edge, source_id, target_id):
                removed_edges += 1
                continue
            kept_edges.append(edge)
        graph_data[key] = kept_edges
    return removed_edges


def _collect_candidate_node_ids(
    nodes: list[dict[str, Any]],
    scorer: Callable[[dict[str, Any]], int],
    *,
    min_score: int,
) -> set[str]:
    candidate_ids: set[str] = set()
    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        if scorer(node) >= min_score:
            candidate_ids.add(node_id)
    return candidate_ids


def _rewrite_pair_edges(
    graph_data: dict[str, Any],
    source_id: str,
    target_id: str,
    source_file: str,
    source_location: str | None,
    *,
    relation: str = "calls",
    preserve_exact_relation: bool = False,
) -> int:
    edge_keys = [key for key in ("links", "edges") if isinstance(graph_data.get(key), list)]
    if not edge_keys:
        graph_data["edges"] = []
        edge_keys = ["edges"]

    removed_edges = 0
    exact_edges: list[dict[str, Any]] = []
    for key in edge_keys:
        original_edges = graph_data[key]
        kept_edges: list[dict[str, Any]] = []
        for edge in original_edges:
            if isinstance(edge, dict) and _edge_matches_pair(edge, source_id, target_id):
                if preserve_exact_relation and _is_exact_edge(edge):
                    exact_edges.append(edge)
                removed_edges += 1
                continue
            kept_edges.append(edge)
        graph_data[key] = kept_edges

    selected_relation = relation
    selected_confidence_score = 1.0
    selected_weight = 1.0
    if preserve_exact_relation and exact_edges:
        selected = _pick_preferred_exact_edge(exact_edges, source_id, target_id, relation)
        relation_value = selected.get("relation")
        if isinstance(relation_value, str) and relation_value:
            selected_relation = relation_value
        selected_confidence_score = _as_float(selected.get("confidence_score"), 1.0)
        selected_weight = _as_float(selected.get("weight"), 1.0)

    primary_key = edge_keys[0]
    graph_data[primary_key].append(
        _deterministic_call_edge(
            source_id,
            target_id,
            source_file,
            source_location,
            relation=selected_relation,
            confidence_score=selected_confidence_score,
            weight=selected_weight,
        )
    )
    return removed_edges


def _enforce_optional_pair(
    graph_data: dict[str, Any],
    nodes: list[dict[str, Any]],
    *,
    source_scorer: Callable[[dict[str, Any]], int],
    target_scorer: Callable[[dict[str, Any]], int],
    source_file: str,
    source_location: str | None,
) -> int:
    source_id = _try_select_node_id(nodes, source_scorer)
    target_id = _try_select_node_id(nodes, target_scorer)
    if source_id is None or target_id is None:
        return 0
    return _rewrite_pair_edges(
        graph_data,
        source_id=source_id,
        target_id=target_id,
        source_file=source_file,
        source_location=source_location,
        preserve_exact_relation=True,
    )


def run_graphify_postpass(
    graph_path: Path,
    *,
    api_path: Path = DEFAULT_API_PATH,
    chat_agent_path: Path = DEFAULT_CHAT_AGENT_PATH,
    mcp_server_path: Path = DEFAULT_MCP_SERVER_PATH,
    output_path: Path | None = None,
) -> PostpassResult:
    """Apply deterministic post-processing to a graph JSON file."""
    evidence = detect_monitor_availability_wiring(chat_agent_path, mcp_server_path)
    if not evidence.is_deterministic:
        raise ValueError("Deterministic monitor_availability wiring could not be proven via AST checks.")
    api_chat_evidence = detect_api_chat_wiring(api_path)
    triage_routing_evidence = detect_triage_routing_wiring(chat_agent_path)
    monitor_scanner_evidence = detect_monitor_scanner_call_wiring(mcp_server_path)

    graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = graph_data.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("Graph JSON must contain a 'nodes' list.")

    source_node_id = _select_node_id(nodes, _score_chat_agent_node, "MCPChatAgent")
    target_node_id = _select_node_id(nodes, _score_monitor_node, MONITOR_TOOL_NAME)

    resolved_chat_path = chat_agent_path.resolve()
    project_root = resolved_chat_path.parents[2] if len(resolved_chat_path.parents) > 2 else resolved_chat_path.parent
    source_file = _as_windows_relative(chat_agent_path, project_root)
    source_location = (
        f"L{evidence.scanner_agent_tools_line}" if evidence.scanner_agent_tools_line is not None else None
    )
    chat_node_candidates = _collect_candidate_node_ids(
        nodes,
        _score_chat_agent_node,
        min_score=180,
    )
    monitor_node_candidates = _collect_candidate_node_ids(
        nodes,
        _score_monitor_node,
        min_score=180,
    )
    removed_edges = 0
    for chat_node_id in chat_node_candidates:
        for monitor_node_id in monitor_node_candidates:
            if chat_node_id == source_node_id and monitor_node_id == target_node_id:
                continue
            removed_edges += _remove_pair_edges(
                graph_data,
                source_id=chat_node_id,
                target_id=monitor_node_id,
            )
    removed_edges += _rewrite_pair_edges(
        graph_data,
        source_id=source_node_id,
        target_id=target_node_id,
        source_file=source_file,
        source_location=source_location,
    )
    api_source_file = _as_windows_relative(api_path, project_root)
    if api_chat_evidence.is_deterministic:
        removed_edges += _enforce_optional_pair(
            graph_data,
            nodes,
            source_scorer=_score_api_chat_handler_node,
            target_scorer=_score_chat_entrypoint_node,
            source_file=api_source_file,
            source_location=(
                f"L{api_chat_evidence.chat_call_line}" if api_chat_evidence.chat_call_line is not None else None
            ),
        )

    if triage_routing_evidence.is_deterministic:
        for route_id, route_line in (
            ("scanner", triage_routing_evidence.scanner_edge_line),
            ("form-agent", triage_routing_evidence.form_edge_line),
            ("notifier", triage_routing_evidence.notifier_edge_line),
        ):
            removed_edges += _enforce_optional_pair(
                graph_data,
                nodes,
                source_scorer=_score_triage_executor_node,
                target_scorer=lambda node, route_id=route_id: _score_triage_target_node(node, route_id),
                source_file=source_file,
                source_location=f"L{route_line}" if route_line is not None else None,
            )

    monitor_source_file = _as_windows_relative(mcp_server_path, project_root)
    if monitor_scanner_evidence.is_deterministic:
        for function_name, call_line in (
            ("scan_portal_availability", monitor_scanner_evidence.scan_portal_availability_line),
            ("compare_snapshots", monitor_scanner_evidence.compare_snapshots_line),
            ("filter_relevant_changes", monitor_scanner_evidence.filter_relevant_changes_line),
            ("deep_scan_date", monitor_scanner_evidence.deep_scan_date_line),
        ):
            removed_edges += _enforce_optional_pair(
                graph_data,
                nodes,
                source_scorer=_score_monitor_node,
                target_scorer=lambda node, function_name=function_name: _score_scanner_chain_target(
                    node, function_name
                ),
                source_file=monitor_source_file,
                source_location=f"L{call_line}" if call_line is not None else None,
            )

    destination = output_path or graph_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{json.dumps(graph_data, ensure_ascii=False, indent=2)}\n", encoding="utf-8")

    return PostpassResult(
        graph_path=graph_path,
        output_path=destination,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        removed_edges=removed_edges,
        evidence=evidence,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for running the graphify post-pass locally."""
    parser = argparse.ArgumentParser(
        description="Upgrade graph edges for deterministic critical availability and chat paths."
    )
    parser.add_argument("graph_path", type=Path, help="Path to graph JSON file.")
    parser.add_argument(
        "--api-path",
        type=Path,
        default=DEFAULT_API_PATH,
        help=f"Path to api.py (default: {DEFAULT_API_PATH})",
    )
    parser.add_argument(
        "--chat-agent-path",
        type=Path,
        default=DEFAULT_CHAT_AGENT_PATH,
        help=f"Path to chat_agent.py (default: {DEFAULT_CHAT_AGENT_PATH})",
    )
    parser.add_argument(
        "--mcp-server-path",
        type=Path,
        default=DEFAULT_MCP_SERVER_PATH,
        help=f"Path to mcp_server.py (default: {DEFAULT_MCP_SERVER_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output file path. Defaults to in-place update.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        result = run_graphify_postpass(
            graph_path=args.graph_path,
            api_path=args.api_path,
            chat_agent_path=args.chat_agent_path,
            mcp_server_path=args.mcp_server_path,
            output_path=args.output,
        )
    except Exception as exc:
        print(f"Postpass failed: {exc}")
        return 1

    print(
        "Postpass complete: "
        f"{result.source_node_id} -> {result.target_node_id} "
        f"(removed {result.removed_edges} conflicting edge(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

