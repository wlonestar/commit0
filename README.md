### Updates
#### Pi backend, one-shot mode, and evaluation integrity:
The `agent` CLI now supports a `pi` backend (`agent config pi --model-name ...`, requires Node.js) alongside `aider`. A new one-shot mode (`--run-one-shot`) hands the whole repo + spec to the agent in a single run, instead of iterating module-by-module. Two integrity guards ship with it: evaluation excludes the test directory and test/lint config files from the agent's patch, and `--sandbox-run` isolates the agent in a fresh repo materialized from `base_commit` (the upstream history, which contains the reference implementation, never reaches the agent), applying the resulting diff back onto the branch afterwards — see [docs/agent.md](docs/agent.md) for details and caveats.

#### Sep 28, 2024:
If you want to use agent with the OpenAI o1 models, please run these installation commands to update packages ``pip install git+https://github.com/wenting-zhao/aider.git``.

---

# Commit0

<a href="https://commit-0.github.io/">Commit0</a> is a from scratch AI coding challenge. Can you create a library from commit 0?

<p align="center">
<img src="docs/arch.png" width="500px">
</p>

<p align="center">
  <a href="https://commit-0.github.io/">
    <img src="https://img.shields.io/badge/Read-Docs-green.svg"/>
  </a>
</p>


The benchmark consists of 57 core Python libraries. The challenge is to rebuild these libraries and pass their unit tests. All libraries have:

* Significant test coverage
* Detailed specification and documentation
* Lint and type checking

Commit0 is an interactive environment that makes it easy to design and test new agents. You can:

* Efficiently run tests in isolated environments
* Distribute testing and development across cloud systems
* Track and log all changes made throughout.

To install Commit0, run:

```
pip install commit0
```

Commit0 provides several commands to facilitate the process of cloning, building, testing, and evaluating repositories. Here's an overview of the available commands:

### Setup

<p align=center>
<img src="docs/commit0.gif" width="500px">
</p>

Use `commit0 setup [OPTIONS] REPO_SPLIT` to clone a repository split.
Available options include:

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `repo_split` | str | Split of repositories to clone | |
| `--dataset-name` | str | Name of the Huggingface dataset | `wentingzhao/commit0_combined` |
| `--dataset-split` | str | Split of the Huggingface dataset | `test` |
| `--base-dir` | str | Base directory to clone repos to | `repos/` |
| `--commit0-config-file` | str | Storing path for stateful commit0 configs | `.commit0.yaml` |

### Build

Use `commit0 build [OPTIONS]` to build the Commit0 split chosen in the Setup stage.
Available options include:

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `--num-workers` | int | Number of workers | `8` |
| `--commit0-config-file` | str | Path to the commit0 dot file | `.commit0.yaml` |
| `--verbose` | int | Verbosity level (1 or 2) | `1` |

### Get Tests

Use `commit0 get-tests REPO_NAME` to get tests for a Commit0 repository.

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `repo_name` | str | Name of the repository to get tests for | |

### Test

Use `commit0 test [OPTIONS] REPO_OR_REPO_PATH [TEST_IDS]` to run tests on a Commit0 repository.
Available options include:

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `repo_or_repo_path` | str | Directory of the repository to test | |
| `test_ids` | str | Test IDs to run | |
| `--branch` | str | Branch to test | |
| `--backend` | str | Backend to use for testing | `modal` |
| `--timeout` | int | Timeout for tests in seconds | `1800` |
| `--num-cpus` | int | Number of CPUs to use | `1` |
| `--reference` | bool | Test the reference commit | `False` |
| `--coverage` | bool | Get coverage information | `False` |
| `--rebuild` | bool | Rebuild an image | `False` |
| `--commit0-config-file` | str | Path to the commit0 dot file | `.commit0.yaml` |
| `--verbose` | int | Verbosity level (1 or 2) | `1` |
| `--stdin` | bool | Read test names from stdin | `False` |

### Evaluate

Use `commit0 evaluate [OPTIONS]` to evaluate the Commit0 split chosen in the Setup stage.
Available options include:

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `--branch` | str | Branch to evaluate | |
| `--backend` | str | Backend to use for evaluation | `modal` |
| `--timeout` | int | Timeout for evaluation in seconds | `1800` |
| `--num-cpus` | int | Number of CPUs to use | `1` |
| `--num-workers` | int | Number of workers to use | `8` |
| `--reference` | bool | Evaluate the reference commit | `False` |
| `--coverage` | bool | Get coverage information | `False` |
| `--commit0-config-file` | str | Path to the commit0 dot file | `.commit0.yaml` |
| `--rebuild` | bool | Rebuild images | `False` |

### Lint

Use `commit0 lint [OPTIONS] REPO_OR_REPO_DIR` to lint files in a repository.
Available options include:

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `repo_or_repo_dir` | str | Directory of the repository to test | |
| `--files` | List[Path] | Files to lint (optional) | |
| `--commit0-config-file` | str | Path to the commit0 dot file | `.commit0.yaml` |
| `--verbose` | int | Verbosity level (1 or 2) | `1` |

### Save

Use `commit0 save [OPTIONS] OWNER BRANCH` to save the Commit0 split to GitHub.
Available options include:

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `owner` | str | Owner of the repository | |
| `branch` | str | Branch to save | |
| `--github-token` | str | GitHub token for authentication | |
| `--commit0-config-file` | str | Path to the commit0 dot file | `.commit0.yaml` |

## Agent

### Config

Use `agent config [OPTIONS] AGENT_NAME` to set up the configuration for an agent.
Available options include:

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `agent_name` | str | Agent backend to use: [aider](https://aider.chat/) or `pi` (requires Node.js, see [docs/agent.md](docs/agent.md)). | `aider` |
| `--model-name` | str | LLM model to use. For aider, check [here](https://aider.chat/docs/llms.html); for pi, use a model string understood by the Pi bridge (e.g. an OpenRouter model). | `claude-3-5-sonnet-20240620` |
| `--use-user-prompt` | bool | Use a custom prompt instead of the default prompt. | `False` |
| `--user-prompt` | str | The prompt sent to agent. | See code for details. |
| `--run-tests` | bool | Run tests after code modifications for feedback. You need to set up `docker` or `modal` before running tests, refer to commit0 docs. | `False` |
| `--max-iteration` | int | Maximum number of agent iterations. | `3` |
| `--run-one-shot` | bool | Hand the whole repo + spec to the agent in a single run, instead of iterating module-by-module. | `False` |
| `--one-shot-timeout` | int | Wall-clock budget (seconds) for the one-shot run; `0` means no limit. | `0` |
| `--sandbox-run` | bool | Anti-cheat: run the agent in a clean sandbox repo created from `base_commit` and apply the resulting diff back onto the branch; the local clone stays reusable. | `False` |
| `--use-repo-info` | bool | Include the repository information. | `False` |
| `--max-repo-info-length` | int | Maximum length of the repository information to use. | `10000` |
| `--use-unit-tests-info` | bool | Include the unit tests information. | `False` |
| `--max-unit-tests-info-length` | int | Maximum length of the unit tests information to use. | `10000` |
| `--use-spec-info` | bool | Include the spec information. | `False` |
| `--max-spec-info-length` | int | Maximum length of the spec information to use. | `10000` |
| `--use-lint-info` | bool | Include the lint information. | `False` |
| `--max-lint-info-length` | int | Maximum length of the lint information to use. | `10000` |
| `--run-entire-dir-lint` | bool | Run the lint on the entire directory. | `False` |
| `--record-test-for-each-commit` | bool | Record the test for each commit. | `False` |
| `--topo-sort-dependencies` | bool | Topologically sort the dependencies of the repository. | `True` |
| `--add-import-module-to-context` | bool | Add the import module code to the context. | `True` |
| `--pre-commit-config-path` | str | Path to the pre-commit config file. This is needed for running `lint`. | `.pre-commit-config.yaml` |
| `--agent-config-file` | str | Path to write the agent config. | `.agent.yaml` |

### Running

Use `agent run [OPTIONS] BRANCH` to execute an agent on a specific branch.
Available options include:

| Argument | Type | Description | Default |
|----------|------|-------------|---------|
| `branch` | str | Branch to run the agent on, you can specific the name of the branch | |
| `--override-previous-changes` | bool | Override the previous agent changes on `branch`, or run continuously on the new changes. | `False` |
| `--backend` | str | Test backend to run the agent on, ignore this option if you are not adding `run_tests` option to agent. | `modal` |
| `--agent-config-file` | str | Path to the agent config file. | `.agent.yaml` |
| `--commit0-config-file` | str | Path to the commit0 config file. | `.commit0.yaml` |
| `--log-dir` | str | Log directory to store the logs. | `logs/agent` |
| `--max-parallel-repos` | int | Maximum number of repositories for agent to run in parallel. Running in sequential if set to 1. | `1` |
| `--display-repo-progress-num` | int | Number of repo progress displayed when running. | `5` |
| `--show-rich-progress` | bool | Display the agent progress with rich. | `True` |
