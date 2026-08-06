# pi_client

Python wrapper around the Pi Agent SDK bridge (`src/agent.mts`), used by the
`pi` agent backend (see `docs/agent.md`).

Spawns `node agent.mts` via asyncio subprocess, feeds a JSON request on
stdin, and streams the agent's text output back from stdout. After the run
ends, the bridge emits the final `SessionStats` (session id, session file,
message/tool counts, tokens, cost, context usage) as one JSON line on stderr,
captured into `client.session_state`.

## Requirements

* Node.js (the bridge is a TypeScript file run by `node`)
* API credentials for the configured model (e.g. `OPENROUTER_API_KEY`)

## Usage

```python
import asyncio
from pi_client import PiClient, PiClientConfig

config = PiClientConfig(
    model="openrouter/deepseek/deepseek-v4-flash-0731",
    thinking_level="high",
    retries=2,              # only transient network/API failures are retried
    message_timeout=600,    # seconds without output before the run is
                            # considered hung (None disables the watchdog)
    session_dir=None,       # defaults to <cwd>/.pi/sessions on the bridge side
)
client = PiClient(config)

result = asyncio.run(client.run("list files", cwd="/path/to/project", timeout=600))
print(result)

state = client.get_session_state()
if state is not None:
    print(f"cost: ${state.cost}, tokens: {state.tokens.total}")
```

## Notes

* The bridge is spawned in its own process group; on timeout or failure the
  whole group (including grandchildren forked by the agent's bash tool) is
  SIGKILLed, so no orphan processes are left behind.
* `PiClient` instances are stateless across calls and safe to share
  concurrently; `session_state` reflects the most recent run.
* Errors raise `PiAgentError` (with a `retryable` flag) or
  `AgentTimeoutError` when the caller-set `timeout` budget is exceeded.
