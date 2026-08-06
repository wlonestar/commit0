from dataclasses import dataclass


@dataclass
class AgentConfig:
    agent_name: str
    model_name: str
    use_user_prompt: bool
    user_prompt: str
    use_topo_sort_dependencies: bool
    add_import_module_to_context: bool
    use_repo_info: bool
    max_repo_info_length: int
    use_unit_tests_info: bool
    max_unit_tests_info_length: int
    use_spec_info: bool
    max_spec_info_length: int
    use_lint_info: bool
    run_entire_dir_lint: bool
    max_lint_info_length: int
    pre_commit_config_path: str
    run_tests: bool
    max_iteration: int
    record_test_for_each_commit: bool
    # One-shot mode: hand the whole repo + spec to the agent in a single run,
    # instead of iterating file-by-file / test-by-test.
    run_one_shot: bool = False
    # Wall-clock budget (seconds) per one-shot attempt; 0 means no limit.
    # Note the effective ceiling is retries (2) x this value.
    one_shot_timeout: int = 7200
    # Anti-cheat: run the agent in a fresh sandbox repo materialized from
    # base_commit; the resulting diff is applied back onto the branch.
    # The original clone keeps its full history and can be re-run without
    # re-cloning.
    sandbox_run: bool = False
    # Pi backend: thinking effort level (off|minimal|low|medium|high|xhigh|max).
    # "high" can make reasoning models burn the whole output budget on a
    # single thinking turn (stopReason=length); lower it if that happens.
    thinking_level: str = "high"
