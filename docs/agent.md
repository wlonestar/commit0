## Running

Commit0 provides a command-line `agent` for configuring and
running AI agents to assist with code development and testing.
In this example we use [Aider](https://aider.chat/) as the
baseline code completion agent

```bash
pip install aider-chat
```

First we assume there is an underlying `commit0`
project that is configured. To create a new project,
run the commit0 `setup` command.

```bash
commit0 setup lite
```

Next we need to configure the backend for the agent.
We support two backends: `aider` (baseline) and `pi`
(a tool-using agent bridged through the Pi Agent SDK,
see `pi_client/`). Config can also be used to pass in arguments.

```bash
export ANTHROPIC_API_KEY="..."
agent config aider
```

For the `pi` backend, you need Node.js installed and a model
string understood by the Pi bridge (e.g. an OpenRouter model):

```bash
export OPENROUTER_API_KEY="..."
agent config pi --model-name openrouter/deepseek/deepseek-v4-flash-0731
```

The default thinking effort is `high`. On reasoning models with a
limited output budget this can backfire: the model may burn the whole
output limit on a single thinking turn (`stopReason=length`) and
produce nothing. The bridge detects this and nudges the agent to
continue (up to 3 times, then fails loudly), but if it recurs, lower
the effort:

```bash
agent config pi --model-name ... --thinking-level medium
```

Finally we run the underlying agent. This will create a display
that shows the current progress of the agent. Specify the branch
you want to commit changes on.

```bash
agent run BRANCH
```

### One-shot mode

By default the agent iterates module-by-module (or test-file-by-test-file),
a decomposition dating back to small-context models. If you want to
evaluate an agent's end-to-end capability, one-shot mode hands the
whole repository plus the spec to the agent in a single run and lets
it explore, implement, and commit by itself. Enable it via `agent config`:

```bash
agent config pi --model-name openrouter/... --run-one-shot --one-shot-timeout 7200
```

or add the following to `.agent.yaml` (or your agent config file):

```yaml
run_one_shot: true
one_shot_timeout: 7200   # wall-clock budget in seconds; 0 = no limit
```

For a fair one-shot evaluation, combine it with the anti-cheat guard
described below:

```bash
agent config pi --model-name openrouter/... \
  --run-one-shot --one-shot-timeout 7200 --sandbox-run
```

(`.agent.yaml` files written by older versions may contain a removed
`purge_history` key; it is ignored.)

In one-shot mode the harness commits the agent's work onto the branch
after the run (pi does not auto-commit; aider does), so evaluation
sees the final state. Logs and session files are kept under the log
directory, never inside the evaluated repo.

### Anti-cheat: isolating the agent from repo history

The cloned repo contains the full upstream git history, including the
reference implementation. An autonomous agent with shell access can
recover it with `git log` / `git diff` / `git checkout`. Enable
`--sandbox-run` to isolate the agent from it:

`--sandbox-run` materializes `base_commit` into a fresh directory as a
brand-new single-commit repo (`git archive` + `git init`). The agent
works there; its own object store never contains the reference
implementation. After the run, the sandbox's diff against its base is
applied back onto the evaluation branch and committed. The original
clone keeps its full history, so re-runs work without re-cloning:

```bash
agent config pi --model-name openrouter/... --run-one-shot --sandbox-run
```

The sandbox workspace and the extracted patch are kept under
`<log_dir>/one_shot/workspace` and `<log_dir>/one_shot/sandbox.patch`
for auditing.

This only closes the git-history channel. The libraries are public PyPI
packages, so a networked agent could still fetch the original source
(`pip download`, GitHub). Closing that channel requires network
isolation at the backend level, which is currently not enforced. As a
detective control, audit the agent's session logs (kept in the log
directory) for suspicious `git`/`pip` usage.

### Test integrity guard

During evaluation, the patch extracted from the agent's branch excludes
the test directory and test/lint config files (`conftest.py`,
`pytest.ini`, `.pre-commit-config.yaml`). Agent edits to these files
are therefore ignored at eval time, which closes the reward-hacking
path of weakening tests or lint rules. Note this makes scores strictly
incomparable with runs predating this guard.

### Extending
Refer to `class Agents` in `agent/agents.py`. You can design your own agent by inheriting `Agents` class and implement the `run` method.

## Notes


* Aider automatically retries certain API errors. For details, see [here](https://github.com/paul-gauthier/aider/blob/75e1d519da9b328b0eca8a73ee27278f1289eadb/aider/sendchat.py#L17).
* When increasing `--max-parallel-repos`, be mindful of aider's [60-second retry timeout](https://github.com/paul-gauthier/aider/blob/75e1d519da9b328b0eca8a73ee27278f1289eadb/aider/sendchat.py#L39). Set this value according to your API tier to avoid RateLimitErrors stopping processes.
* Currently, agent will skip file with more than 1500 lines. See `agent/agent_utils.py#L199` for details.
* Running a full `all` commit0 split costs approximately $100 with Claude Sonnet 3.5.
