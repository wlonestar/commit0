# Self-evolution

`self-evolution/run.py` 管理 Commit-0 的 baseline 和后续自演化。当前 checkout 的 `logs/agent/` 没有有效运行产物时，脚本会先在当前 checkout 自动运行一次仓库 Agent、评测和复盘；已有产物时，脚本才读取上一轮证据，让 Pi 修改下一轮使用的提示词或 Agent 实现，在独立 worktree 中提交修改，然后运行新一轮 Agent、评测和复盘。

脚本每次只执行一轮，不会自动循环。

## 运行前准备

先按项目根目录的 `tips.md` 完成环境和数据准备，至少需要：

- 已激活的 Python 虚拟环境，以及 `uv pip install ".[agent]"` 安装的依赖。
- `npm install` 生成的 `node_modules/`，Pi 的 Node bridge 需要从这里加载依赖。
- `commit0 setup` 和 `commit0 build` 已完成，`.commit0.yaml` 中的 `base_dir` 可用。
- `.agent.yaml` 已配置为需要评测的 Agent 模式。
- 模型供应商的 API key 已写入当前 shell 环境。

后续迭代的新 worktree 从当前 `HEAD` 创建。第一次运行前，应先提交 `self-evolution/`、`scripts/analysis.py` 和 `agent/` 中准备投入实验的代码。未提交的源码不会出现在后续新 worktree 中。`.agent.yaml` 和 `.commit0.yaml` 虽然被 Git 忽略，脚本会单独复制。

冷启动默认会调用整批仓库 Agent、一次完整评测和一次复盘 Agent；后续完整迭代还会先调用一次演化 Agent。先检查模型、并发数和超时设置，避免误触发高成本任务。

## 快速开始

在当前迭代的 checkout 中运行：

```bash
python self-evolution/run.py
```

如果 `logs/agent/` 不存在、为空，或没有 `.agent.yaml`、Agent 日志、session JSONL 等有效运行产物，这条命令会直接在当前 checkout 启动 baseline：

```text
agent run -> commit0 evaluate -> analysis
```

baseline 完成后，在同一个 checkout 再执行一次 `python self-evolution/run.py`，脚本才会创建第一个候选 worktree，读取 baseline 产物并开始演化。

已有上一轮产物时，只准备并提交演化修改，不启动下一轮仓库 Agent 和评测，可以运行：

```bash
python self-evolution/run.py --skip-next-iteration
```

冷启动时使用 `--skip-next-iteration` 不会创建 worktree，也不会启动 baseline。已有产物时，该参数仍会创建并提交演化 worktree，只跳过新一轮仓库 Agent、评测和复盘。

候选 worktree 已经跑完 Agent、评测和复盘后，下一轮要读取它的产物，应从刚生成的 worktree 再次启动：

```bash
cd .worktrees/worktree-<timestamp>
python self-evolution/run.py
```

worktree 实际位于主 checkout 的 `.worktrees/` 下。即使从某个 worktree 继续运行，新的 worktree 也会创建为它的同级目录，不会逐轮嵌套。

也可以显式指定上一轮所在的 checkout：

```bash
python /path/to/self-evolution/run.py \
  --project-root /path/to/.worktrees/worktree-<timestamp>
```

`--project-root` 的默认值由 `run.py` 所在位置决定，不是当前 shell 的工作目录。重复运行原 checkout 中的脚本，会继续读取原 checkout 的日志。

## 一轮执行流程

### 0. 自动补齐 baseline

脚本首先递归检查当前 checkout 的 `logs/agent/`。只要找到仓库 Agent 写出的配置快照、`pi.log`、`aider.log` 或 session JSONL，就认为已有可供演化的上一轮证据。

没有这些产物时，脚本不会启动无证据的演化 Agent，也不会创建候选 worktree，而是给本轮生成独立的实验分支名：

```text
self-evolution-baseline-20260809-153754-852379
```

随后在当前 checkout 直接执行仓库 Agent、评测和复盘。产物保存在当前 checkout 的 `logs/` 中。完成后再次运行脚本，才进入下面的常规演化流程。

### 1. 创建 worktree 和实验分支

已有上一轮 Agent 产物时，脚本通过 Git common directory 找到主 checkout，在下面创建一对同名迭代资源：

```text
.worktrees/worktree-20260809-153754-852379/
self-evolution-20260809-153754-852379
```

时间戳包含微秒。若路径或分支已经存在，脚本会追加数字后缀，避免覆盖已有迭代。

### 2. 准备运行环境

脚本把上一轮 checkout 中被忽略的 `.agent.yaml` 和 `.commit0.yaml` 复制到新 worktree。如果源 checkout 有 `node_modules/`，新 worktree 会建立一个指向它的符号链接。

后续命令默认通过当前解释器启动：

```bash
python -m agent ...
python -m commit0 ...
```

这样可以继续使用当前虚拟环境中的依赖，同时优先导入新 worktree 下的 `agent/`、`commit0/` 和 `pi_client/` 源码。演化 Agent 对这些源码的修改会在下一轮生效。

### 3. 收集上一轮证据

上一轮 `logs/` 下的关键文件会复制到新 worktree 的 `logs/previous/`，目录层级保持不变。当前收集范围包括：

- 所有 `.log` 文件。
- Pi session JSONL。
- 每个仓库记录的 `.agent.yaml`。
- `iteration-analysis.md`。
- pytest 的 `report.json` 和 `pytest_exit_code.txt`。

已有的 `logs/previous/` 不会再次复制，避免出现 `previous/previous/` 并让目录逐轮膨胀。

### 4. 运行演化 Agent

脚本创建独立的 Pi client，以新 worktree 为 `cwd`。提示词要求它先查找 `logs/previous/**/iteration-analysis.md`，再用原始日志、session 和 pytest 报告核对结论。

演化 Agent 会检查完整的一次性模式提示词链路：

```text
.agent.yaml:user_prompt
  -> agent_utils.get_message()
  -> agent_utils.get_one_shot_message()
  -> run_agent.py 或 run_agent_no_rich.py
  -> PiAgents._build_prompt()
```

`.agent.yaml:user_prompt` 只是其中一个输入。Agent 可以修改 `.agent.yaml`，也可以修改 `agent/` 下的共享提示词组装逻辑。

Pi 从调用时传入的 `cwd` 查找 `.pi/skills/`。仓库 Agent 开启 `sandbox_run` 后，`cwd` 是每个仓库的 sandbox workspace，不是 Commit-0 的框架 worktree。只在框架根目录生成 `.pi/skills/<name>/SKILL.md`，不会自动影响仓库 Agent。采用 skill 方案时，还需要实现到 sandbox 的资源传递或加载逻辑。

### 5. 提交演化修改

演化 Agent 不负责提交。脚本统一暂存并创建如下提交：

```text
self-evolution: prepare iteration <timestamp>
```

`logs/` 和 `node_modules` 不会进入提交。`.agent.yaml` 默认被项目忽略，只有内容被演化 Agent 修改或新建时，脚本才会强制暂存它。如果没有任何可提交修改，脚本报错并保留 worktree 和日志，方便排查。

### 6. 运行仓库 Agent

脚本在新 worktree 中执行与 `tips.md` 对应的命令：

```bash
python -m agent run <branch> \
  --backend=local \
  --max-parallel-repos=16
```

同一个实验分支名会用于 `.commit0.yaml` 指向的每个目标仓库。目标仓库是各自独立的 Git 仓库，它们的提交不会写入框架 worktree 的 Git 历史。

### 7. 运行评测

仓库 Agent 全部结束后，脚本执行：

```bash
python -m commit0 evaluate \
  --backend=local \
  --branch=<branch> \
  --timeout=1800
```

评测生成的逐仓库报告位于 `logs/pytest/`。评测命令、退出码、标准输出和标准错误还会合并保存到 `logs/evaluation/<branch>/evaluate.log`。

### 8. 运行复盘 Agent

评测结束后，`scripts/analysis.py` 会启动一个新的 Pi client。它只收集当前分支的证据，包括：

- 仓库 Agent 的配置快照、`pi.log` 或 `aider.log`，以及 session JSONL。
- pytest 报告、退出码、测试输出、覆盖率和运行日志。
- `commit0 evaluate` 的控制台输出。
- `processing_summary_<branch>.json`，如果 rich 运行模式生成了该文件。
- 当前有效提示词相关源码和 `.agent.yaml`。

复盘 Agent 输出 Markdown 报告，内容包括整体和逐仓库结果、有效做法、失败原因、重试和超时等效率问题，以及下一轮提示词或 skill 调整建议。

如果 `commit0 evaluate` 返回非零退出码，脚本仍会先完成复盘，再把评测错误返回给调用者。

## 主要产物

下面是一次常规演化运行的代表性目录。具体文件取决于 Agent 配置、仓库数量和评测后端。首次 baseline 不创建 worktree；除 `previous/`、`self-evolution/` 和演化后的源码外，同类产物直接写入当前 checkout。

```text
<main-checkout>/.worktrees/worktree-<timestamp>/
├── .agent.yaml
├── .commit0.yaml
├── node_modules -> <source-checkout>/node_modules
├── processing_summary_<branch>.json
├── logs/
│   ├── previous/
│   │   └── ...                         # 上一轮关键证据的目录快照
│   ├── self-evolution/
│   │   ├── pi.log                      # 演化 Agent 的文本输出
│   │   ├── session-stats.json          # 演化 Agent 的 token、成本和上下文统计
│   │   └── sessions/*.jsonl            # 演化 Agent 的完整 session
│   ├── agent/<repo>/<branch>/<time>/
│   │   ├── .agent.yaml                 # 该仓库实际使用的配置快照
│   │   └── one_shot/
│   │       ├── pi.log                  # 仓库 Agent 输出和 session 统计
│   │       ├── sessions/*.jsonl
│   │       ├── spec/                   # 从 base commit 提取的规格说明
│   │       ├── workspace/              # sandbox_run 使用的临时仓库
│   │       └── sandbox.patch           # 应用回目标仓库的补丁
│   ├── pytest/<repo>/<branch>/<hash>/
│   │   ├── report.json                 # pytest JSON 报告
│   │   ├── pytest_exit_code.txt
│   │   ├── test_output.txt
│   │   ├── run_pytest.log
│   │   ├── patch.diff
│   │   └── eval.sh
│   ├── evaluation/<branch>/
│   │   └── evaluate.log                # evaluate 命令、退出码、stdout 和 stderr
│   └── analysis/<branch>/
│       ├── artifacts.txt               # 复盘 Agent 使用的证据清单
│       ├── iteration-analysis.md       # 本轮复盘报告
│       ├── session-stats.json
│       └── sessions/*.jsonl
└── ...                                 # 演化后并已提交的源码或提示词
```

### Git 中会保存什么

| 内容 | 是否进入框架 worktree 的演化提交 | 说明 |
|---|---:|---|
| `agent/`、`pi_client/` 等源码修改 | 是 | 由演化 Agent 产生并统一提交 |
| `.pi/skills/` | 是 | 只有实现了 sandbox 可见性后才会影响仓库 Agent |
| `.agent.yaml` | 条件性保存 | 仅在演化 Agent 修改或新建时强制暂存 |
| `.commit0.yaml` | 否 | 只作为运行配置复制 |
| `logs/` | 否 | 作为迭代证据保留在 worktree 中 |
| `node_modules` 链接 | 否 | 只用于复用 Node 依赖 |
| 目标仓库的实验提交 | 否 | 保存在 `.commit0.yaml:base_dir` 指向的独立仓库中 |

## 常用参数

完整参数以 `python self-evolution/run.py --help` 为准。

| 参数 | 默认值 | 用途 |
|---|---|---|
| `--project-root` | `run.py` 所在 checkout | 指定上一轮日志和配置所在的 checkout |
| `--model` | PiClient 默认模型 | 演化 Agent 使用的模型，也可用 `SELF_EVOLUTION_MODEL` 设置 |
| `--analysis-model` | PiClient 默认模型 | 复盘 Agent 使用的模型，也可用 `SELF_EVOLUTION_ANALYSIS_MODEL` 设置 |
| `--thinking-level` | `high` | 演化 Agent 的思考等级 |
| `--analysis-thinking-level` | `high` | 复盘 Agent 的思考等级 |
| `--retries` | `2` | 演化和复盘 Agent 的最大尝试次数 |
| `--timeout` | `3600` | 演化 Agent 单次尝试的总超时，设为 `0` 表示不限制 |
| `--analysis-timeout` | `1800` | 复盘 Agent 单次尝试的总超时，设为 `0` 表示不限制 |
| `--message-timeout` | `1200` | 演化 Agent 无输出超时，设为 `0` 表示关闭 |
| `--analysis-message-timeout` | `1200` | 复盘 Agent 无输出超时，设为 `0` 表示关闭 |
| `--backend` | `local` | 仓库 Agent 和评测使用的后端 |
| `--max-parallel-repos` | `16` | 并行处理的仓库数 |
| `--evaluation-timeout` | `1800` | 传给每个仓库评测任务的超时 |
| `--agent-command` | `python -m agent` | 覆盖 Agent 可执行文件，参数只接受一个可执行路径 |
| `--commit0-command` | `python -m commit0` | 覆盖 Commit-0 可执行文件，参数只接受一个可执行路径 |
| `--skip-next-iteration` | 关闭 | 已有产物时只完成演化和提交；冷启动时跳过自动 baseline |

指定不同的演化和复盘模型：

```bash
python self-evolution/run.py \
  --model openrouter/provider/evolution-model \
  --analysis-model openrouter/provider/analysis-model
```

## 单独运行复盘

仓库 Agent 和评测已经手动完成时，可以只运行复盘脚本：

```bash
python scripts/analysis.py <branch> \
  --project-root /path/to/iteration-worktree
```

复盘脚本要求该分支至少有一项运行或评测产物。它会重新生成 `logs/analysis/<branch>/artifacts.txt` 和 `iteration-analysis.md`，并保留新的 Pi session。

## 失败后的检查位置

- baseline 仓库 Agent 失败：查看当前 checkout 的 `logs/agent/<repo>/<baseline-branch>/`。
- 演化 Agent 失败：查看 `logs/self-evolution/` 和其中的 session。
- 没有可提交修改：查看 `logs/self-evolution/pi.log`，worktree 会保留。
- 仓库 Agent 失败：查看 `logs/agent/<repo>/<branch>/`。
- 评测失败：查看 `logs/evaluation/<branch>/evaluate.log` 和对应的 `logs/pytest/`。
- 复盘 Agent 失败：查看 `logs/analysis/<branch>/sessions/`。

脚本不会自动删除失败或已完成的 worktree，也不会清理目标仓库中的实验分支。
