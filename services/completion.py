"""Best-effort artifact storage and completion notifications."""

import logging
import os
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from services.notice import send_notice
from services.s3 import upload_to_r2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompletionResult:
    """Outcome of completion side effects."""

    object_key: str | None
    notified: bool
    uploaded_files: tuple[str, ...] = ()


def _safe_segment(value: str) -> str:
    return value.replace("\\", "_").replace("/", "_").strip(". ") or "unknown"


_EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache", "workspace"}


def _is_uploadable(path: Path, directory: Path) -> bool:
    relative = path.relative_to(directory)
    return path.is_file() and not _EXCLUDED_PARTS.intersection(relative.parts)


def _archive(directory: Path, destination: Path) -> None:
    """Archive result files without duplicating an agent's sandbox checkout."""
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(directory.rglob("*")):
            if not _is_uploadable(path, directory):
                continue
            relative = path.relative_to(directory)
            archive.add(path, arcname=Path(directory.name) / relative, recursive=False)


def _log_files(directory: Path) -> list[Path]:
    """Return logs and session artifacts, including nested Pi sessions."""
    return [
        path
        for path in sorted(directory.rglob("*"))
        if _is_uploadable(path, directory)
        and (
            path.suffix.lower() in {".jsonl", ".log"}
            or path.name == "session_stats.json"
        )
    ]


def _object_name(
    prefix: str, event: str, branch: str, project: str, *parts: str
) -> str:
    """Build a stable, readable R2 key from an artifact's relative path."""
    safe_parts = [_safe_segment(part) for part in (prefix, event, branch, project)]
    for part in parts:
        safe_parts.extend(
            _safe_segment(segment) for segment in part.split("/") if segment
        )
    return "/".join(part for part in safe_parts if part)


def store_and_notify(
    event: str,
    project: str,
    branch: str,
    artifact_dir: Path,
    details: str = "",
) -> CompletionResult:
    """Store completion artifacts in R2, then send a Bark notification.

    Both integrations are optional and best-effort. A storage or notification
    failure is logged but never changes the project/evaluation result.
    """
    load_dotenv()
    directory = Path(artifact_dir)
    object_key = None
    uploaded_files: list[str] = []
    storage_note = "storage not configured"

    if directory.is_dir():
        prefix = os.getenv("R2_PREFIX", "commit0").strip("/")
        try:
            with tempfile.TemporaryDirectory(prefix="commit0-") as temporary_dir:
                archive_name = f"{_safe_segment(directory.name)}.tar.gz"
                archive_path = Path(temporary_dir) / archive_name
                _archive(directory, archive_path)
                object_key = upload_to_r2(
                    archive_path,
                    _object_name(prefix, event, branch, project, archive_name),
                )
                if object_key:
                    uploaded_files.append(object_key)
        except Exception:
            logger.exception("Could not store %s archive for %s", event, project)

        # Upload logs and Pi sessions as individual objects as well. This makes
        # JSONL sessions and logs directly inspectable without downloading the
        # complete archive.
        for path in _log_files(directory):
            try:
                relative = path.relative_to(directory).as_posix()
                key = upload_to_r2(
                    path,
                    _object_name(prefix, event, branch, project, relative),
                )
                if key:
                    uploaded_files.append(key)
            except Exception:
                logger.exception("Could not store artifact %s", path)

        if uploaded_files:
            log_count = sum(
                Path(key).suffix.lower() in {".jsonl", ".log"}
                or Path(key).name == "session_stats.json"
                for key in uploaded_files
            )
            storage_note = (
                f"stored {len(uploaded_files)} objects"
                f" ({log_count} session/log files)"
            )
    else:
        storage_note = f"artifact directory missing: {directory}"
        logger.warning(storage_note)

    message_parts = [f"project: {project}", f"branch: {branch}"]
    if details:
        message_parts.append(details)
    message_parts.append(storage_note)

    notified = False
    try:
        notified = send_notice(f"Commit0 {event} finished", "\n".join(message_parts))
    except Exception:
        logger.exception("Could not send %s notification for %s", event, project)

    return CompletionResult(
        object_key=object_key,
        notified=notified,
        uploaded_files=tuple(uploaded_files),
    )
