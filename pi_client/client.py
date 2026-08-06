"""Python wrapper around the Pi Agent SDK bridge (agent.mts).

Spawns ``node agent.mts`` via asyncio subprocess, feeds a JSON request on
stdin, and streams the agent's text output back from stdout. After the run
ends, the bridge emits the final SessionStats (session id, session file,
message/tool counts, tokens, cost, context usage) as one JSON line on stderr,
captured into ``client.session_state``.

Usage::

    config = PiClientConfig(model="openrouter/moonshotai/kimi-k3", retries=3)
    client = PiClient(config)

    result = await client.run("list files", cwd="/path/to/project")
    print(result)
"""

from __future__ import annotations

import asyncio
import codecs
import json
import os
import re
import signal
from contextlib import suppress
from pathlib import Path
from typing import AsyncIterator, Optional
from pydantic import BaseModel, ConfigDict, Field, ValidationError

AGENT_SCRIPT = Path(__file__).resolve().parent.parent / "src" / "agent.mts"

# Errors that are worth retrying: transient network/API failures.
_TRANSIENT_PATTERN = re.compile(
    r"timed? ?out|econn\w+|socket|\b5\d\d\b|overloaded|unavailable|internal error",
    re.IGNORECASE,
)


class PiAgentError(RuntimeError):
    """Raised when the Node agent bridge exits with an error.

    Attributes:
        retryable: True if the failure looks transient (network, 5xx)
            and a retry has a reasonable chance of succeeding.
        details: extra structured context (returncode, raw stderr, ...).
    """

    def __init__(self, message: str, *, retryable: bool = False, details: Optional[dict] = None):
        super().__init__(message)
        self.retryable = retryable
        self.details = details or {}


class AgentTimeoutError(PiAgentError):
    """Total time budget (``timeout``) exceeded. Not retried: the caller set the budget."""


class AgentIdleTimeoutError(PiAgentError):
    """No output for ``message_timeout`` seconds; the model stream likely hung. Retryable."""

    def __init__(self, message: str, *, details: Optional[dict] = None):
        super().__init__(message, retryable=True, details=details)


def _build_request(
    prompt: str,
    cwd: str,
    model: Optional[str],
    thinking_level: Optional[str],
    session_dir: Optional[str],
) -> bytes:
    request: dict = {"cwd": cwd, "prompt": prompt}
    if model:
        request["model"] = model
    if thinking_level:
        request["thinkingLevel"] = thinking_level
    if session_dir:
        request["session_dir"] = session_dir
    return json.dumps(request).encode()


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the agent process and its whole process group.

    The bridge is spawned with start_new_session=True (own process group), so
    killing the group also takes down grandchildren forked by the agent's
    bash tool. Falls back to killing just the process.
    """
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        with suppress(ProcessLookupError, OSError):
            proc.kill()


def _classify_error(returncode: Optional[int], stderr: str) -> PiAgentError:
    """Turn a non-zero bridge exit into a PiAgentError with a retryable flag."""
    message = stderr.strip()
    # The bridge reports structured errors as a single JSON line on stderr.
    for line in reversed(message.splitlines()):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "error" in parsed:
            message = str(parsed["error"])
            break
    retryable = bool(_TRANSIENT_PATTERN.search(message))
    return PiAgentError(
        f"agent failed (exit {returncode}): {message}",
        retryable=retryable,
        details={"returncode": returncode, "stderr": stderr.strip()},
    )


class SessionTokens(BaseModel):
    """Token usage aggregated over a session run."""

    model_config = ConfigDict(populate_by_name=True)

    input: int = 0
    output: int = 0
    cache_read: int = Field(default=0, alias="cacheRead")
    cache_write: int = Field(default=0, alias="cacheWrite")
    total: int = 0


class ContextUsage(BaseModel):
    """Context window usage at the end of a run."""

    model_config = ConfigDict(populate_by_name=True)

    #: Estimated context tokens; None if unknown (e.g. right after compaction).
    tokens: Optional[int] = None
    context_window: int = Field(default=0, alias="contextWindow")
    #: Percentage of the context window used; None if tokens is unknown.
    percent: Optional[float] = None


class SessionStats(BaseModel):
    """Final per-run statistics emitted by the bridge on stderr.

    Mirrors the SDK's ``SessionStats``; field aliases match the wire format.
    """

    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    #: Path to the session JSONL file; None if the session was not persisted.
    session_file: Optional[str] = Field(default=None, alias="sessionFile")
    user_messages: int = Field(default=0, alias="userMessages")
    assistant_messages: int = Field(default=0, alias="assistantMessages")
    tool_calls: int = Field(default=0, alias="toolCalls")
    tool_results: int = Field(default=0, alias="toolResults")
    total_messages: int = Field(default=0, alias="totalMessages")
    tokens: SessionTokens = Field(default_factory=SessionTokens)
    #: Total cost in USD.
    cost: float = 0.0
    context_usage: Optional[ContextUsage] = Field(default=None, alias="contextUsage")


def _parse_state_line(line: str) -> Optional[SessionStats]:
    """Parse the bridge's SessionStats line from stderr, or return None.

    The bridge emits the bare SessionStats object once the run has ended,
    identified by its characteristic keys. Error objects (``{"error": ...}``),
    Node warnings, and malformed stats lines are left in the stderr output
    for error reporting.
    """
    if not line.startswith("{"):
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not (isinstance(parsed, dict) and "sessionId" in parsed and "totalMessages" in parsed):
        return None
    with suppress(ValidationError):
        return SessionStats.model_validate(parsed)
    return None


def _backoff_seconds(attempt: int) -> float:
    """Linear backoff between retries: 3s per step, capped at 10s."""
    return min(3.0 * attempt, 10.0)


class PiClientConfig(BaseModel):
    model: str = "openrouter/deepseek/deepseek-v4-flash-0731"
    thinking_level: str = "high"
    retries: int = 2
    message_timeout: Optional[float] = 1200
    node_bin: str = "node"
    session_dir: Optional[str] = None


class PiClient:
    """Pi agent client holding default options, so callers don't repeat them per call.

    Instances are stateless across calls and safe to share concurrently.
    """

    def __init__(self, config: PiClientConfig):
        self.config = config
        #: SessionStats from the most recent run; None if it never reached
        #: a clean end (killed, timed out, or crashed).
        self.session_state: Optional[SessionStats] = None


    async def run(
        self,
        prompt: str,
        cwd: str,
        timeout: int | None = None
    ) -> str:
        """Run the agent to completion and return the full text output.

        Per-call args override client defaults.

        Args:
            timeout: total time budget in seconds, per attempt. None means no limit.

        Config-driven behavior (from the client config, not per-call):
            retries: number of attempts (1 = no retry). Only errors flagged as
                retryable (transient network/API failure, idle hang) are retried,
                with linear backoff (3s per step, capped at 10s).
            session_dir: directory for session JSONL files. Defaults to
                ``<cwd>/.pi/sessions`` on the bridge side.

        Raises:
            AgentTimeoutError: ``timeout`` exceeded (not retried).
            PiAgentError: the agent failed; the last error is raised after all retries.
        """

        async def _collect() -> str:
            parts: list[str] = []
            async for delta in self._query(prompt, cwd):
                parts.append(delta)
            return "".join(parts)

        last_error: Optional[PiAgentError] = None
        for attempt in range(1, self.config.retries + 1):
            try:
                if timeout is not None:
                    try:
                        async with asyncio.timeout(timeout):
                            text = await _collect()
                    except TimeoutError:
                        raise AgentTimeoutError(
                            f"agent timed out after {timeout}s",
                            details={"cwd": cwd, "model": self.config.model, "timeout": timeout, "attempt": attempt},
                        )
                else:
                    text = await _collect()
                return text
            except PiAgentError as e:
                last_error = e
                if not e.retryable or attempt >= self.config.retries:
                    raise
                await asyncio.sleep(_backoff_seconds(attempt))

        raise last_error  # type: ignore[misc]


    def get_session_state(self) -> Optional[SessionStats]:
        """SessionStats (session id, message/tool counts, tokens, cost, context
        usage) from the last run, or None if the run never reached a clean end."""
        return self.session_state


    async def _query(self, prompt: str, cwd: str) -> AsyncIterator[str]:
        """Run the agent and yield text deltas as they stream in.

        ``message_timeout`` (client-level): seconds without any stdout output
        before the model is considered hung and the process group is killed.
        None disables the watchdog.

        Raises:
            AgentIdleTimeoutError: no output for ``message_timeout`` seconds (retryable).
            PiAgentError: the agent process exited non-zero.
        """
        proc = await asyncio.create_subprocess_exec(
            self.config.node_bin,
            str(AGENT_SCRIPT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            # Own process group, so cleanup can SIGKILL the agent's bash-tool
            # grandchildren too instead of leaving orphans behind.
            start_new_session=True,
        )
        assert proc.stdin and proc.stdout and proc.stderr
        proc.stdin.write(
            _build_request(
                prompt, cwd,
                self.config.model,
                self.config.thinking_level,
                self.config.session_dir
            )
        )
        proc.stdin.close()

        decoder = codecs.getincrementaldecoder("utf-8")()
        self.session_state = None

        async def _read_stderr() -> str:
            """Drain stderr concurrently, picking the SessionStats line out.

            The bridge emits the final SessionStats as one JSON line on stderr
            after the run ends; it is captured into ``self.session_state``.
            Remaining lines (Node warnings, the JSON error object) are kept
            for error reporting. Reading stderr while stdout streams also
            prevents a deadlock if the bridge ever fills the stderr pipe
            buffer.
            """
            lines: list[str] = []
            while True:
                if not proc.stderr:
                    continue
                raw = await proc.stderr.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").rstrip("\r\n")
                state = _parse_state_line(line)
                if state is not None:
                    self.session_state = state
                    continue
                lines.append(line)
            return "\n".join(lines)

        stderr_task = asyncio.create_task(_read_stderr())
        try:
            while True:
                try:
                    if self.config.message_timeout is not None:
                        chunk = await asyncio.wait_for(proc.stdout.read(256), timeout=self.config.message_timeout)
                    else:
                        chunk = await proc.stdout.read(256)
                except asyncio.TimeoutError:
                    raise AgentIdleTimeoutError(
                        f"no output for {self.config.message_timeout}s, model stream likely hung",
                        details={"cwd": cwd, "model": self.config.model, "idle_timeout": self.config.message_timeout},
                    )
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    yield text

            stderr = await stderr_task
            await proc.wait()
            if proc.returncode != 0:
                raise _classify_error(proc.returncode, stderr)
        finally:
            _kill_process_group(proc)
            if proc.returncode is None:
                await proc.wait()
            if not stderr_task.done():
                stderr_task.cancel()
                with suppress(asyncio.CancelledError):
                    await stderr_task


async def main():
    config = PiClientConfig(model="deepseek/deepseek-v4-flash")
    client = PiClient(config)
    result = await client.run("hi, where is current dir?", "/tmp")
    print(result)

    state = client.get_session_state()
    if state is None:
        return
    print(
        f'sessionFile: {state.session_file if state.session_file else ""}\n'
        f'sessionId: {state.session_id}\n'
        f'tokens: {{\n'
        f'  input: {state.tokens.input}\n'
        f'  output: {state.tokens.output}\n'
        f'  cacheRead: {state.tokens.cache_read}\n'
        f'  cacheWrite: {state.tokens.cache_write}\n'
        f'  total: {state.tokens.total}\n'
        f'}}\n'
        f'cost: ${state.cost}\n'
    )


if __name__ == '__main__':
    asyncio.run(main())
