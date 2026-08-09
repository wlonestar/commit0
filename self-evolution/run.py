"""Bootstrap or run one Commit-0 self-evolution iteration."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence


# ``python self-evolution/run.py`` puts only ``self-evolution`` on sys.path.
# Add the checkout root so the project-local Pi wrapper remains importable even
# though it is not one of the packages included in the wheel configuration.
CHECKOUT_ROOT = Path(__file__).resolve().parents[1]
if str(CHECKOUT_ROOT) in sys.path:
    sys.path.remove(str(CHECKOUT_ROOT))
sys.path.insert(0, str(CHECKOUT_ROOT))

from pi_client import PiClient, PiClientConfig  # noqa: E402
from scripts.analysis import analyze_iteration  # noqa: E402


ARTIFACT_SUFFIXES = {".jsonl", ".log"}
ARTIFACT_NAMES = {
    ".agent.yaml",
    "iteration-analysis.md",
    "pytest_exit_code.txt",
    "report.json",
}
RUNTIME_CONFIG_NAMES = (".agent.yaml", ".commit0.yaml")
AGENT_RUN_ARTIFACT_NAMES = {".agent.yaml", "aider.log", "pi.log"}
AGENT_RUN_ARTIFACT_SUFFIXES = {".jsonl"}


@dataclass(frozen=True)
class Worktree:
    """The checkout and experiment branch used for one benchmark iteration."""

    path: Path
    branch: str
    iteration: str


def _run(
    command: Sequence[os.PathLike[str] | str],
    *,
    cwd: Path,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [os.fspath(part) for part in command],
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def find_project_root(start: Path) -> Path:
    """Return the Git worktree root containing *start*."""
    result = _run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start.resolve(),
        capture_output=True,
    )
    return Path(result.stdout.strip()).resolve()


def has_agent_run_artifacts(project_root: Path) -> bool:
    """Return whether ``logs/agent`` contains evidence of an earlier run."""
    agent_logs = project_root / "logs" / "agent"
    if not agent_logs.is_dir():
        return False

    return any(
        not path.is_symlink()
        and path.is_file()
        and (
            path.name in AGENT_RUN_ARTIFACT_NAMES
            or path.suffix.lower() in AGENT_RUN_ARTIFACT_SUFFIXES
        )
        for path in agent_logs.rglob("*")
    )


def create_baseline_iteration(
    project_root: Path, stamp: str | None = None
) -> Worktree:
    """Describe a cold-start benchmark run in the current checkout."""
    iteration = stamp or datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    return Worktree(
        path=project_root,
        branch=f"self-evolution-baseline-{iteration}",
        iteration=iteration,
    )


def _worktrees_root(project_root: Path) -> Path:
    """Use the primary checkout for sibling worktrees, even when rerun in one."""
    result = _run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=project_root,
        capture_output=True,
    )
    common_git_dir = Path(result.stdout.strip())
    if not common_git_dir.is_absolute():
        common_git_dir = (project_root / common_git_dir).resolve()
    return common_git_dir.parent / ".worktrees"


def _branch_exists(project_root: Path, branch: str) -> bool:
    result = _run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=project_root,
        check=False,
    )
    return result.returncode == 0


def create_worktree(project_root: Path, stamp: str | None = None) -> Worktree:
    """Create a unique sibling worktree and branch starting at the current HEAD."""
    iteration = stamp or datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    worktrees_root = _worktrees_root(project_root)
    worktrees_root.mkdir(parents=True, exist_ok=True)

    suffix = 0
    while True:
        unique_iteration = iteration if suffix == 0 else f"{iteration}-{suffix}"
        path = worktrees_root / f"worktree-{unique_iteration}"
        branch = f"self-evolution-{unique_iteration}"
        if not path.exists() and not _branch_exists(project_root, branch):
            break
        suffix += 1

    _run(
        ["git", "worktree", "add", "-b", branch, path, "HEAD"],
        cwd=project_root,
    )
    return Worktree(path=path, branch=branch, iteration=unique_iteration)


def copy_runtime_configs(project_root: Path, worktree: Path) -> None:
    """Prepare ignored runtime files needed by commands in the worktree."""
    for name in RUNTIME_CONFIG_NAMES:
        source = project_root / name
        if source.is_file() and not source.is_symlink():
            shutil.copy2(source, worktree / name)

    # The evolved Python sources must run from the worktree, but the Pi bridge
    # resolves its npm dependency relative to worktree/src/agent.mts. Reuse the
    # installed dependency tree without copying it into every iteration.
    source_node_modules = project_root / "node_modules"
    target_node_modules = worktree / "node_modules"
    if source_node_modules.is_dir() and not target_node_modules.exists():
        target_node_modules.symlink_to(
            source_node_modules.resolve(), target_is_directory=True
        )


def _is_iteration_artifact(path: Path) -> bool:
    return path.name in ARTIFACT_NAMES or path.suffix.lower() in ARTIFACT_SUFFIXES


def collect_previous_artifacts(project_root: Path, worktree: Path) -> list[Path]:
    """Copy prior logs, session JSONL, and agent snapshots to ``logs/previous``."""
    source_root = project_root / "logs"
    destination_root = worktree / "logs" / "previous"
    destination_root.mkdir(parents=True, exist_ok=True)
    if not source_root.is_dir():
        return []

    copied: list[Path] = []
    for source in sorted(source_root.rglob("*")):
        if source.is_symlink() or not source.is_file():
            continue
        relative = source.relative_to(source_root)
        # A worktree from an earlier self-evolution run already has its own
        # snapshot. Skipping it prevents logs/previous/previous/... growth.
        if relative.parts and relative.parts[0] == "previous":
            continue
        if not _is_iteration_artifact(source):
            continue
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied


def build_evolution_prompt(artifacts: Sequence[Path]) -> str:
    """Build the analysis-and-edit prompt sent to Pi."""
    artifact_summary = (
        f"There are {len(artifacts)} copied artifacts under logs/previous."
        if artifacts
        else "No prior artifacts were found; infer improvements from the current configuration and code."
    )
    return f"""You are preparing the next self-evolution iteration for this Commit-0 checkout.

{artifact_summary}

Analyze the previous iteration analysis, agent logs, Pi session JSONL, and pytest reports in logs/previous. Start with iteration-analysis.md when present, then verify its conclusions against raw artifacts. Pay particular attention to repeated failure modes, tool-use mistakes, test outcomes, timeouts, and places where the agent's instructions were ambiguous.

Before editing, trace the effective one-shot prompt end to end. It is composed by agent/agent_utils.py (get_message and get_one_shot_message), the run mode in agent/run_agent.py or agent/run_agent_no_rich.py, and agent/agents.py (PiAgents._build_prompt). The YAML user_prompt is only one input to that pipeline.

Edit this working tree directly and implement a focused improvement at the prompt layer supported by the evidence. This may mean changing the shared one-shot composition in agent/, changing .agent.yaml while keeping it valid for AgentConfig, or both. Keep rich and no-rich execution behavior consistent.

Pi resources are discovered relative to the cwd passed to Pi. In sandboxed one-shot runs that cwd is the per-repository sandbox workspace, not this framework worktree. Do not create a framework-local skill and assume benchmark agents will see it. If a skill is the evidence-backed solution, use .pi/skills/<skill-name>/SKILL.md and also implement the resource propagation/loading needed to make it available from the sandbox cwd. Do not put skills in skills/, .agents/skills/, or logs/.

Prefer a small, evidence-backed change over a broad rewrite. Do not modify logs/previous, generated session files, tips.md, or repository history. Do not commit; the orchestration script will review and commit your working-tree changes. You must make the edits, not merely describe recommendations in your response.
"""


async def run_evolution_agent(
    worktree: Worktree,
    artifacts: Sequence[Path],
    *,
    model: str | None,
    thinking_level: str,
    retries: int,
    message_timeout: float | None,
    timeout: int | None,
) -> str:
    """Run Pi in the new worktree and persist its text output and session stats."""
    run_log_dir = worktree.path / "logs" / "self-evolution"
    session_dir = run_log_dir / "sessions"
    run_log_dir.mkdir(parents=True, exist_ok=True)

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
        build_evolution_prompt(artifacts),
        cwd=str(worktree.path),
        timeout=timeout,
    )
    (run_log_dir / "pi.log").write_text(output, encoding="utf-8")

    state = client.get_session_state()
    if state is not None:
        (run_log_dir / "session-stats.json").write_text(
            state.model_dump_json(indent=2, by_alias=True) + "\n",
            encoding="utf-8",
        )
    return output


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def commit_evolution_changes(
    worktree: Worktree,
    *,
    initial_agent_config_digest: str | None,
) -> str:
    """Stage generated changes, commit them, and return the commit SHA."""
    # Diagnostics are inputs/outputs of the evolution run, never part of the
    # evolved commit. The explicit exclusion keeps that invariant even if a
    # checkout does not ignore logs/ itself.
    _run(
        [
            "git",
            "add",
            "-A",
            "--",
            ".",
            ":(exclude)logs",
            ":(exclude)node_modules",
        ],
        cwd=worktree.path,
    )

    # .agent.yaml is intentionally ignored by the main project. Force-add it
    # only when Pi actually changed or created it, rather than committing the
    # copied baseline configuration as a false-positive evolution.
    agent_config = worktree.path / ".agent.yaml"
    if (
        _file_digest(agent_config) != initial_agent_config_digest
        and agent_config.is_file()
    ):
        _run(["git", "add", "-f", "--", ".agent.yaml"], cwd=worktree.path)

    staged = _run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=worktree.path,
        check=False,
    )
    if staged.returncode == 0:
        raise RuntimeError(
            f"Pi produced no committable changes in {worktree.path}; its output is in logs/self-evolution/pi.log"
        )
    if staged.returncode != 1:
        raise subprocess.CalledProcessError(staged.returncode, staged.args)

    _run(
        [
            "git",
            "commit",
            "-m",
            f"self-evolution: prepare iteration {worktree.iteration}",
        ],
        cwd=worktree.path,
    )
    result = _run(["git", "rev-parse", "HEAD"], cwd=worktree.path, capture_output=True)
    return result.stdout.strip()


def run_next_iteration(
    worktree: Worktree,
    *,
    agent_command: str | None,
    backend: str,
    max_parallel_repos: int,
) -> None:
    """Launch the next benchmark iteration using the command documented in tips.md."""
    command = (
        [agent_command]
        if agent_command is not None
        else [sys.executable, "-m", "agent"]
    )
    _run(
        [
            *command,
            "run",
            worktree.branch,
            f"--backend={backend}",
            f"--max-parallel-repos={max_parallel_repos}",
        ],
        cwd=worktree.path,
    )


def run_evaluation(
    worktree: Worktree,
    *,
    commit0_command: str | None,
    backend: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Evaluate the completed branch and persist the command's full output."""
    command_prefix = (
        [commit0_command]
        if commit0_command is not None
        else [sys.executable, "-m", "commit0"]
    )
    command = [
        *command_prefix,
        "evaluate",
        f"--backend={backend}",
        f"--branch={worktree.branch}",
        f"--timeout={timeout}",
    ]
    result = _run(
        command,
        cwd=worktree.path,
        check=False,
        capture_output=True,
    )

    output_dir = worktree.path / "logs" / "evaluation" / worktree.branch
    output_dir.mkdir(parents=True, exist_ok=True)
    sections = [f"$ {' '.join(command)}\n", f"exit_code: {result.returncode}\n"]
    if result.stdout:
        sections.append(f"\n--- stdout ---\n{result.stdout}")
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        sections.append(f"\n--- stderr ---\n{result.stderr}")
        print(
            result.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )
    (output_dir / "evaluate.log").write_text("".join(sections), encoding="utf-8")
    return result


def run_benchmark_and_analysis(
    worktree: Worktree, args: argparse.Namespace
) -> None:
    """Run one repository-agent benchmark, evaluate it, and summarize it."""
    print(f"Launching agent run for {worktree.branch}", flush=True)
    run_next_iteration(
        worktree,
        agent_command=args.agent_command,
        backend=args.backend,
        max_parallel_repos=args.max_parallel_repos,
    )
    print(f"Evaluating {worktree.branch}", flush=True)
    evaluation = run_evaluation(
        worktree,
        commit0_command=args.commit0_command,
        backend=args.backend,
        timeout=args.evaluation_timeout,
    )
    print(f"Analyzing iteration {worktree.branch}", flush=True)
    analysis = asyncio.run(
        analyze_iteration(
            worktree.path,
            worktree.branch,
            model=args.analysis_model,
            thinking_level=args.analysis_thinking_level,
            retries=args.retries,
            message_timeout=args.analysis_message_timeout,
            timeout=args.analysis_timeout,
        )
    )
    print(analysis.output.rstrip())
    print(f"Saved iteration analysis to {analysis.summary_path}", flush=True)
    if evaluation.returncode != 0:
        raise subprocess.CalledProcessError(
            evaluation.returncode,
            evaluation.args,
            output=evaluation.stdout,
            stderr=evaluation.stderr,
        )


def _optional_positive(value: str) -> int | None:
    parsed = int(value)
    return parsed if parsed > 0 else None


def _optional_positive_float(value: str) -> float | None:
    parsed = float(value)
    return parsed if parsed > 0 else None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for a self-evolution run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=CHECKOUT_ROOT,
        help="Git checkout containing the previous iteration (default: this checkout)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("SELF_EVOLUTION_MODEL"),
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
        default=3600,
        help="Total Pi run timeout in seconds; 0 disables it",
    )
    parser.add_argument(
        "--agent-command",
        default=None,
        help="Agent executable override (default: run worktree sources with python -m agent)",
    )
    parser.add_argument(
        "--commit0-command",
        default=None,
        help="Commit0 executable override (default: run worktree sources with python -m commit0)",
    )
    parser.add_argument("--backend", default="local")
    parser.add_argument("--max-parallel-repos", type=int, default=16)
    parser.add_argument(
        "--evaluation-timeout",
        type=int,
        default=1800,
        help="Per-repository timeout passed to commit0 evaluate",
    )
    parser.add_argument(
        "--analysis-model",
        default=os.environ.get("SELF_EVOLUTION_ANALYSIS_MODEL"),
        help="Post-evaluation Pi model override",
    )
    parser.add_argument("--analysis-thinking-level", default="high")
    parser.add_argument(
        "--analysis-message-timeout",
        type=_optional_positive_float,
        default=1200.0,
        help="Post-evaluation analysis idle timeout; 0 disables it",
    )
    parser.add_argument(
        "--analysis-timeout",
        type=_optional_positive,
        default=1800,
        help="Total post-evaluation analysis timeout; 0 disables it",
    )
    parser.add_argument(
        "--skip-next-iteration",
        action="store_true",
        help=(
            "With prior logs, prepare and commit only; with no logs, skip the "
            "automatic baseline"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Bootstrap a baseline or prepare and launch one evolved iteration."""
    args = parse_args(argv)
    project_root = find_project_root(args.project_root)

    if not has_agent_run_artifacts(project_root):
        if args.skip_next_iteration:
            print(
                "No prior agent artifacts found; skipped the automatic baseline "
                "as requested",
                flush=True,
            )
            return 0

        baseline = create_baseline_iteration(project_root)
        print(
            f"No prior agent artifacts found; running baseline {baseline.branch} "
            f"in {baseline.path}",
            flush=True,
        )
        run_benchmark_and_analysis(baseline, args)
        print(
            "Baseline complete. Run self-evolution/run.py again from this "
            "checkout to create the first evolved worktree.",
            flush=True,
        )
        return 0

    worktree = create_worktree(project_root)
    print(f"Created {worktree.path} on branch {worktree.branch}", flush=True)

    copy_runtime_configs(project_root, worktree.path)
    initial_agent_config_digest = _file_digest(worktree.path / ".agent.yaml")
    artifacts = collect_previous_artifacts(project_root, worktree.path)
    print(f"Collected {len(artifacts)} previous artifacts", flush=True)

    asyncio.run(
        run_evolution_agent(
            worktree,
            artifacts,
            model=args.model,
            thinking_level=args.thinking_level,
            retries=args.retries,
            message_timeout=args.message_timeout,
            timeout=args.timeout,
        )
    )
    commit_sha = commit_evolution_changes(
        worktree,
        initial_agent_config_digest=initial_agent_config_digest,
    )
    print(f"Committed self-evolution changes as {commit_sha}", flush=True)

    if args.skip_next_iteration:
        print("Skipped the next agent iteration as requested", flush=True)
    else:
        run_benchmark_and_analysis(worktree, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
