"""Single-command graphify pipeline with deterministic post-pass."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from wiesn_agent.graphify_postpass import (
    DEFAULT_CHAT_AGENT_PATH,
    DEFAULT_MCP_SERVER_PATH,
    PostpassResult,
    run_graphify_postpass,
)


@dataclass(frozen=True)
class GraphifyPipelineResult:
    """Result summary for a pipeline run."""

    extraction_path: Path
    graph_path: Path
    report_path: Path
    html_path: Path | None
    summary_path: Path
    node_count: int
    edge_count: int
    community_count: int
    postpass: PostpassResult


def _import_graphify_modules() -> dict[str, Any]:
    try:
        from graphify.analyze import god_nodes, suggest_questions, surprising_connections
        from graphify.build import build_from_json
        from graphify.cluster import cluster, score_all
        from graphify.detect import detect
        from graphify.export import to_html, to_json
        from graphify.extract import collect_files, extract
        from graphify.report import generate
    except Exception as exc:  # pragma: no cover - runtime dependency check
        raise RuntimeError(
            "graphify is required for this command. Install it first (e.g. pip install graphifyy)."
        ) from exc

    return {
        "god_nodes": god_nodes,
        "suggest_questions": suggest_questions,
        "surprising_connections": surprising_connections,
        "build_from_json": build_from_json,
        "cluster": cluster,
        "score_all": score_all,
        "detect": detect,
        "to_html": to_html,
        "to_json": to_json,
        "collect_files": collect_files,
        "extract": extract,
        "generate": generate,
    }


def _resolve_input_path(project_root: Path, input_path: str) -> Path:
    candidate = Path(input_path)
    if candidate.is_absolute():
        return candidate
    return (project_root / candidate).resolve()


def _resolve_scope_roots(
    project_root: Path,
    *,
    include_web_source: bool = False,
    include_tests: bool = False,
) -> list[Path]:
    roots = [project_root / "src"]
    if include_web_source:
        roots.append(project_root / "web" / "src")
    if include_tests:
        roots.append(project_root / "tests")

    scoped_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            scoped_roots.append(resolved)
    return scoped_roots


def _collect_files_from_entries(
    project_root: Path,
    entries: Sequence[Path | str],
    collect_files: Any,
) -> list[Path]:
    collected: list[Path] = []
    seen: set[Path] = set()
    for entry in entries:
        resolved = _resolve_input_path(project_root, str(entry))
        if not resolved.exists():
            continue
        if resolved.is_dir():
            for nested in collect_files(resolved):
                nested_resolved = Path(nested).resolve()
                if nested_resolved.is_file() and nested_resolved not in seen:
                    seen.add(nested_resolved)
                    collected.append(nested_resolved)
        elif resolved.is_file() and resolved not in seen:
            seen.add(resolved)
            collected.append(resolved)
    return collected


def _collect_code_files(
    project_root: Path,
    detection: dict[str, Any],
    collect_files: Any,
    *,
    scoped_roots: Sequence[Path],
) -> list[Path]:
    scoped_files = _collect_files_from_entries(project_root, scoped_roots, collect_files)
    if scoped_files:
        return scoped_files

    files = detection.get("files", {})
    code_entries = files.get("code", []) if isinstance(files, dict) else []
    return _collect_files_from_entries(project_root, code_entries, collect_files)


def _label_communities(G: Any, communities: dict[int, list[str]]) -> dict[int, str]:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "this",
        "that",
        "these",
        "those",
        "file",
        "files",
        "page",
        "section",
        "image",
        "code",
        "test",
        "tests",
        "class",
        "function",
        "module",
        "component",
        "agent",
        "tool",
        "wiesn",
    }

    labels: dict[int, str] = {}
    used = Counter()
    for cid, node_ids in communities.items():
        words = Counter()
        for node_id in node_ids[:250]:
            node_data = G.nodes[node_id]
            label = str(node_data.get("label", ""))
            for token in re.findall(r"[A-Za-z][A-Za-z0-9]+", label.lower()):
                if token in stop_words or len(token) < 4:
                    continue
                words[token] += 1

        top = [word for word, _ in words.most_common(2)]
        if len(top) == 2:
            base = f"{top[0].title()} {top[1].title()}"
        elif len(top) == 1:
            base = f"{top[0].title()} Group"
        else:
            base = f"Community {cid}"
        used[base] += 1
        labels[cid] = base if used[base] == 1 else f"{base} {used[base]}"
    return labels


def run_graphify_pipeline(
    *,
    project_root: Path,
    output_dir: Path,
    chat_agent_path: Path = DEFAULT_CHAT_AGENT_PATH,
    mcp_server_path: Path = DEFAULT_MCP_SERVER_PATH,
    skip_html: bool = False,
    include_web_source: bool = False,
    include_tests: bool = False,
) -> GraphifyPipelineResult:
    """Run graph generation, then post-pass, then report/html export."""
    graphify = _import_graphify_modules()

    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    detection = graphify["detect"](project_root)
    scoped_roots = _resolve_scope_roots(
        project_root,
        include_web_source=include_web_source,
        include_tests=include_tests,
    )
    code_files = _collect_code_files(
        project_root,
        detection,
        graphify["collect_files"],
        scoped_roots=scoped_roots,
    )
    if not code_files:
        raise ValueError("No code files detected for graph generation.")

    extraction = graphify["extract"](code_files)
    extraction_path = output_dir / "extraction.json"
    extraction_path.write_text(
        f"{json.dumps(extraction, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )

    postpass_result = run_graphify_postpass(
        graph_path=extraction_path,
        chat_agent_path=chat_agent_path.resolve(),
        mcp_server_path=mcp_server_path.resolve(),
    )
    patched_extraction = json.loads(extraction_path.read_text(encoding="utf-8"))

    G = graphify["build_from_json"](patched_extraction)
    if G.number_of_nodes() == 0:
        raise ValueError("Graph generation produced zero nodes.")

    communities = graphify["cluster"](G)
    cohesion = graphify["score_all"](G, communities)
    labels = _label_communities(G, communities)
    gods = graphify["god_nodes"](G)
    surprises = graphify["surprising_connections"](G, communities)
    questions = graphify["suggest_questions"](G, communities, labels)
    tokens = {
        "input": int(patched_extraction.get("input_tokens", 0) or 0),
        "output": int(patched_extraction.get("output_tokens", 0) or 0),
    }

    report = graphify["generate"](
        G,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        detection,
        tokens,
        str(project_root),
        suggested_questions=questions,
    )

    graph_path = output_dir / "graph.json"
    report_path = output_dir / "GRAPH_REPORT.md"
    html_path = output_dir / "graph.html"
    summary_path = output_dir / "graphify_pipeline_summary.json"

    graphify["to_json"](G, communities, str(graph_path))
    report_path.write_text(report, encoding="utf-8")

    html_output: Path | None = None
    if not skip_html and G.number_of_nodes() <= 5000:
        graphify["to_html"](G, communities, str(html_path), community_labels=labels)
        html_output = html_path

    summary = {
        "project_root": str(project_root),
        "scope": {
            "roots": [str(path) for path in scoped_roots],
            "include_web_source": include_web_source,
            "include_tests": include_tests,
        },
        "code_files": len(code_files),
        "graph": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "communities": len(communities),
        },
        "postpass": {
            "source_node_id": postpass_result.source_node_id,
            "target_node_id": postpass_result.target_node_id,
            "removed_edges": postpass_result.removed_edges,
            "evidence": {
                "scanner_tools_line": postpass_result.evidence.scanner_tools_line,
                "filter_tools_line": postpass_result.evidence.filter_tools_line,
                "scanner_agent_tools_line": postpass_result.evidence.scanner_agent_tools_line,
                "mcp_stdio_line": postpass_result.evidence.mcp_stdio_line,
                "monitor_tool_line": postpass_result.evidence.monitor_tool_line,
            },
        },
        "output": {
            "extraction": str(extraction_path),
            "graph": str(graph_path),
            "report": str(report_path),
            "html": str(html_output) if html_output else None,
        },
    }
    summary_path.write_text(
        f"{json.dumps(summary, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )

    return GraphifyPipelineResult(
        extraction_path=extraction_path,
        graph_path=graph_path,
        report_path=report_path,
        html_path=html_output,
        summary_path=summary_path,
        node_count=G.number_of_nodes(),
        edge_count=G.number_of_edges(),
        community_count=len(communities),
        postpass=postpass_result,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the graphify pipeline."""
    parser = argparse.ArgumentParser(
        description="Run graph generation -> post-pass -> report/html export."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Project root to analyze (default: current directory).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("graphify-out"),
        help="Output directory for graph artifacts (default: graphify-out).",
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
        "--skip-html",
        action="store_true",
        help="Skip HTML export.",
    )
    parser.add_argument(
        "--include-web-source",
        action="store_true",
        help="Include web/src in extraction scope.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include tests in extraction scope.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        result = run_graphify_pipeline(
            project_root=args.project_root,
            output_dir=args.output_dir,
            chat_agent_path=args.chat_agent_path,
            mcp_server_path=args.mcp_server_path,
            skip_html=args.skip_html,
            include_web_source=args.include_web_source,
            include_tests=args.include_tests,
        )
    except Exception as exc:
        print(f"Pipeline failed: {exc}")
        return 1

    print(
        "Pipeline complete: "
        f"{result.node_count} nodes, {result.edge_count} edges, {result.community_count} communities. "
        f"Post-pass removed {result.postpass.removed_edges} conflicting edge(s)."
    )
    print(f"Graph: {result.graph_path}")
    print(f"Report: {result.report_path}")
    if result.html_path is not None:
        print(f"HTML: {result.html_path}")
    else:
        print("HTML: skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
