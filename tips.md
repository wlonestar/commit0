```shell
# step1: config env
uv venv --python 3.12
source .venv/bin/activate
uv sync
# uv pip install .
# uv pip install ".[agent]"
npm install

# step2: config docker image
uv run python -m commit0 setup lite
uv run python -m commit0 build
uv run python -m agent config pi --model-name deepseek/deepseek-v4-flash --run-one-shot --one-shot-timeout 3600 --run-tests --sandbox-run

# step3: run
uv run python -m agent run <branch> --backend=local --max-parallel-repos=16

# step4: evaluate
uv run python -m commit0 evaluate --backend=local --branch=<branch>
```
