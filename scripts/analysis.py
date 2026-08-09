"""Summarize one Commit-0 iteration from its agent and evaluation artifacts."""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


CHECKOUT_ROOT = Path(__file__).resolve().parents[1]
if str(CHECKOUT_ROOT) in sys.path:
    sys.path.remove(str(CHECKOUT_ROOT))
sys.path.insert(0, str(CHECKOUT_ROOT))

from pi_client import PiClient, PiClientConfig  # noqa: E402


AGENT_ARTIFACT_NAMES = {
    ".agent.yaml",
    "aider.log",
    "eval_results.json",
    "pi.log",
}
AGENT_ARTIFACT_SUFFIXES = {".jsonl"}
EVALUATION_ARTIFACT_NAMES = {
    "coverage.json",
    "evaluate.log",
    "pytest_exit_code.txt",
    "report.json",
    "run_pytest.log",
    "test_output.txt",
}
PROMPT_SOURCE_PATHS = (
    Path(".agent.yaml"),
    Path("agent/agent_utils.py"),
    Path("agent/agents.py"),
    Path("agent/run_agent.py"),
    Path("agent/run_agent_no_rich.py"),
)


@dataclass(frozen=True)
class AnalysisResult:
    """The persisted summary and the evidence used to produce it."""

    summary_path: Path
    artifacts: tuple[Path, ...]
    output: str


def find_project_root(start: Path) -> Path:
    """Return the Git worktree root containing *start*."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start.resolve(),
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def _collect_named_files(root: Path, names: set[str]) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        path
        for path in root.rglob("*")
        if not path.is_symlink() and path.is_file() and path.name in names
    ]


def collect_iteration_artifacts(project_root: Path, branch: str) -> list[Path]:
    """Enumerate analysis inputs belonging only to *branch*."""
    artifacts: list[Path] = []

    agent_root = project_root / "logs" / "agent"
    if agent_root.is_dir():
        for repository in agent_root.iterdir():
            branch_root = repository / branch
            if not branch_root.is_dir():
                continue
            for path in branch_root.rglob("*"):
                if path.is_symlink() or not path.is_file():
                    continue
                if (
                    path.name in AGENT_ARTIFACT_NAMES
                    or path.suffix.lower() in AGENT_ARTIFACT_SUFFIXES
                ):
                    artifacts.append(path)

    pytest_root = project_root / "logs" / "pytest"
    if pytest_root.is_dir():
        for repository in pytest_root.iterdir():
            artifacts.extend(
                _collect_named_files(repository / branch, EVALUATION_ARTIFACT_NAMES)
            )

    artifacts.extend(
        _collect_named_files(
            project_root / "logs" / "evaluation" / branch,
            EVALUATION_ARTIFACT_NAMES,
        )
    )

    processing_summary = project_root / f"processing_summary_{branch}.json"
    if processing_summary.is_file() and not processing_summary.is_symlink():
        artifacts.append(processing_summary)

    if artifacts:
        for relative_path in PROMPT_SOURCE_PATHS:
            prompt_source = project_root / relative_path
            if prompt_source.is_file() and not prompt_source.is_symlink():
                artifacts.append(prompt_source)

    # A path can be reached twice only when callers arrange overlapping roots,
    # but deterministic de-duplication also keeps the manifest stable in tests.
    return sorted(set(artifacts))


def build_analysis_prompt(branch: str, manifest_path: Path) -> str:
    """Build a read-only, evidence-oriented iteration analysis prompt."""
    return f"""Analyze Commit-0 iteration `{branch}` using the artifact manifest at `{manifest_path.as_posix()}`.

Read the manifest, then inspect the listed effective-prompt source files, agent logs, Pi session JSONL, pytest reports, exit codes, test output, and captured `commit0 evaluate` output. Reconstruct the actual one-shot prompt composition before recommending prompt changes. Stay within the listed evidence for this branch. Recalculate or cross-check aggregate results from report.json where possible instead of trusting prose in agent responses.

Return a concise Markdown report with these sections:

1. Outcome: aggregate pass rate and repository-level results, explicitly noting missing or failed evaluations.
2. What worked: behaviors or instructions correlated with successful repositories.
3. Failure analysis: recurring root-cause categories with concrete repository and artifact evidence.
4. Efficiency: avoidable retries, timeouts, token/tool-use issues, and cost information when available.
5. Next iteration: prioritized, actionable changes to the effective one-shot prompt pipeline. Distinguish changes to agent_utils.get_message/get_one_shot_message, PiAgents._build_prompt, and .agent.yaml instead of treating the YAML prompt as the whole instruction. If recommending a Pi skill, account for the fact that sandboxed one-shot Pi runs discover resources from the per-repository sandbox cwd. Separate high-confidence changes from hypotheses.

Do not edit project files or repository history. Do not propose changes unsupported by the artifacts. Your response itself is the analysis report and will be saved by the caller.
"""


async def analyze_iteration(
    project_root: Path,
    branch: str,
    *,
    model: str | None = None,
    thinking_level: str = "high",
    retries: int = 2,
    message_timeout: float | None = 1200,
    timeout: int | None = 1800,
) -> AnalysisResult:
    """Run a fresh Pi agent over one iteration and persist its Markdown report."""
    project_root = project_root.resolve()
    artifacts = collect_iteration_artifacts(project_root, branch)
    if not artifacts:
        raise FileNotFoundError(f"no artifacts found for iteration {branch!r}")

    output_dir = project_root / "logs" / "analysis" / branch
    session_dir = output_dir / "sessions"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "artifacts.txt"
    manifest_path.write_text(
        "".join(f"{path.relative_to(project_root).as_posix()}\n" for path in artifacts),
        encoding="utf-8",
    )

    config_values: dict[str, object] = {
        "thinking_level": thinking_level,
        "retries": retries,
        "message_timeout": message_timeout,
        "session_dir": str(session_dir),
    }
    if model is not None:
        config_values["model"] = model
    client = PiClient(PiClientConfig(**config_values))
    output = await client.run(
        build_analysis_prompt(branch, manifest_path.relative_to(project_root)),
        cwd=str(project_root),
        timeout=timeout,
    )

    summary_path = output_dir / "iteration-analysis.md"
    summary_path.write_text(output.rstrip() + "\n", encoding="utf-8")
    state = client.get_session_state()
    if state is not None:
        (output_dir / "session-stats.json").write_text(
            state.model_dump_json(indent=2, by_alias=True) + "\n",
            encoding="utf-8",
        )
    return AnalysisResult(summary_path, tuple(artifacts), output)


def _optional_positive(value: str) -> int | None:
    parsed = int(value)
    return parsed if parsed > 0 else None


def _optional_positive_float(value: str) -> float | None:
    parsed = float(value)
    return parsed if parsed > 0 else None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse analysis command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("branch", help="Iteration branch to analyze")
    parser.add_argument("--project-root", type=Path, default=CHECKOUT_ROOT)
    parser.add_argument(
        "--model",
        default=os.environ.get("SELF_EVOLUTION_ANALYSIS_MODEL"),
        help="Pi model override (default: PiClientConfig's model)",
    )
    parser.add_argument("--thinking-level", default="high")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--message-timeout",
        type=_optional_positive_float,
        default=1200.0,
        help="Idle timeout in seconds; 0 disables it",
    )
    parser.add_argument(
        "--timeout",
        type=_optional_positive,
        default=1800,
        help="Total analysis timeout in seconds; 0 disables it",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Analyze one completed iteration and print the saved report location."""
    args = parse_args(argv)
    project_root = find_project_root(args.project_root)
    result = asyncio.run(
        analyze_iteration(
            project_root,
            args.branch,
            model=args.model,
            thinking_level=args.thinking_level,
            retries=args.retries,
            message_timeout=args.message_timeout,
            timeout=args.timeout,
        )
    )
    print(result.output.rstrip())
    print(f"\nSaved analysis to {result.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
