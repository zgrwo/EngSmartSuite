"""run_affected_tests.py 的源文件→测试映射逻辑测试。

映射约定（与脚本 docstring 保持一致）：
  - engine/ → tests/test_engine；services/、core/ → tests/test_services
  - web/ → E2E + 集成测试文件
  - scripts/ → tests/scripts 下 stem 子串匹配（无匹配 = 缺测 fail）
  - tests/ 自身变更 → 直接运行变更文件
  - 文档/配置变更 → skip
  - 未知路径 → fail

返回值约定：map_source_to_tests(path) -> (kind, targets)
  kind ∈ {"run", "skip", "fail"}
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "run_affected_tests.py"
mod = importlib.util.spec_from_file_location("run_affected_tests", SPEC)
run_affected_tests = importlib.util.module_from_spec(mod)
assert mod and mod.loader
mod.loader.exec_module(run_affected_tests)

map_source_to_tests = run_affected_tests.map_source_to_tests


def test_engine_module_maps_to_test_engine_dir():
    assert map_source_to_tests("src/smartsuite/engine/spc_monitor.py") == (
        "run",
        ["tests/test_engine"],
    )
    assert map_source_to_tests("src/smartsuite/engine/root_cause.py") == (
        "run",
        ["tests/test_engine"],
    )


def test_services_and_core_map_to_test_services_dir():
    assert map_source_to_tests("src/smartsuite/services/orchestrator.py") == (
        "run",
        ["tests/test_services"],
    )
    assert map_source_to_tests("src/smartsuite/core/contracts.py") == (
        "run",
        ["tests/test_services"],
    )


def test_web_modules_map_to_e2e_and_integration():
    expected = (
        "run",
        [
            "tests/test_web_e2e.py",
            "tests/test_integration.py",
            "tests/test_integration_chemical.py",
            "tests/test_integration_reliability.py",
            "tests/test_integration_warranty.py",
        ],
    )
    assert map_source_to_tests("src/smartsuite/web/app.py") == expected
    assert map_source_to_tests("src/smartsuite/web/api.py") == expected


def test_cli_maps_to_master_integration():
    assert map_source_to_tests("src/smartsuite/cli.py") == (
        "run",
        ["tests/test_integration.py", "tests/test_master_integration.py", "tests/test_services"],
    )


def test_scripts_stem_match_under_tests_scripts():
    assert map_source_to_tests("scripts/run_affected_tests.py") == (
        "run",
        ["tests/scripts/test_run_affected_tests.py"],
    )
    # 连字符命名归一化为下划线后仍能命中
    assert map_source_to_tests("scripts/validate-commit-msg.sh") == (
        "run",
        ["tests/scripts/test_validate_commit_msg.py"],
    )


def test_scripts_without_matching_test_reports_fail():
    # 新脚本无对应测试 → 缺测 fail（既有脚本已登记豁免）
    assert map_source_to_tests("scripts/new_future_script.py") == ("fail", [])


def test_legacy_scripts_exempted():
    # 既有治理脚本由 CI 直接执行覆盖（豁免清单），不算缺测
    assert map_source_to_tests("scripts/gen_requirements.py") == ("skip", [])
    assert map_source_to_tests("scripts/verify_consistency.py") == ("skip", [])


def test_test_file_change_runs_itself():
    assert map_source_to_tests("tests/test_engine/test_correctness.py") == (
        "run",
        ["tests/test_engine/test_correctness.py"],
    )


def test_template_yaml_maps_to_services_and_workflows():
    assert map_source_to_tests("templates/example_anova.yaml") == (
        "run",
        ["tests/test_services", "tests/test_workflows.py"],
    )


def test_docs_and_config_are_skipped():
    assert map_source_to_tests("rules/api-reference.md") == ("skip", [])
    assert map_source_to_tests("agents.md") == ("skip", [])
    assert map_source_to_tests(".github/workflows/ci.yml") == ("skip", [])
    assert map_source_to_tests("README.md") == ("skip", [])
    assert map_source_to_tests("skills/smartsuite-dev.md") == ("skip", [])


def test_unknown_path_is_failure():
    assert map_source_to_tests("packages/unknown.bin") == ("fail", [])
