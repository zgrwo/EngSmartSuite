/**
 * 跨平台 Python 解释器探测 —— 门禁脚本（`.mjs`）调用 Python 侧时的**唯一**入口。
 *
 * ## 为什么需要它
 *
 * 2026-10-09 发版前审查 P0-11：`check_params_panel.mjs` 把解释器路径写死为
 * `resolve(HERE, '..', '.venv', 'Scripts', 'python.exe')`。该布局**只在 Windows 成立**：
 *   - POSIX venv 的解释器是 `.venv/bin/python`；
 *   - CI 用 `uv run pytest`，仓库内甚至没有 `.venv/Scripts`。
 * 于是脚本在 `execFileSync` 处抛未捕获的 ENOENT，退出码 1，包装测试
 * `assert r.returncode == 0` 失败 —— `ci.yml quick`（每个 PR）必红。
 *
 * 本模块把「找一个能 import smartsuite 的 Python」收敛为一处实现，供多个门禁脚本共用
 * （避免各脚本各写一份会漂移的候选表）。
 *
 * ## 候选顺序（先命中先用）
 *
 * 1. `SMARTSUITE_PYTHON` —— 包装测试注入的 `sys.executable`，**权威来源**
 * 2. 仓库内 venv：`.venv/bin/python`（POSIX）或 `.venv/Scripts/python.exe`（Windows）
 * 3. `VIRTUAL_ENV` 指向的 venv（CI/本地已激活环境）
 * 4. `PATH` 上的 `python3` / `python`（附 `.exe` 变体以适配 Windows）
 *
 * 全部不可用时返回 `null`：**由调用方显式 FAIL 并给出中文原因**，
 * 不得让 ENOENT 以堆栈形式暴露（见 AGENTS.md「错误信息使用中文工艺术语，不暴露 traceback」）。
 */

import { existsSync } from 'node:fs';
import { delimiter, join } from 'node:path';

/** 显式指定解释器的环境变量名（包装测试用它注入 `sys.executable`）。 */
export const PYTHON_ENV = 'SMARTSUITE_PYTHON';

/**
 * 门禁脚本的三态退出码契约（2026-10-09 审查 P1-13）。
 *
 * 旧行为把「环境不满足」与「通过」都记为 `0`，于是真浏览器冒烟在
 * Linux/macOS（无 Edge、无 `.venv/Scripts`）**永久空跑却显示为通过** ——
 * 报告与文档会把这一层算作已有防线（假安全感）。
 */
export const EXIT_OK = 0;
export const EXIT_PROBLEMS = 1;
export const EXIT_ENV_UNSATISFIED = 2;

/**
 * 按优先级列出解释器候选路径（**不去重、不校验存在性** —— 便于单测断言顺序）。
 *
 * @param {{repoRoot?: string, env?: Record<string, string|undefined>}} opts
 * @returns {string[]} 候选绝对/相对路径列表
 */
export function pythonCandidates({ repoRoot, env = process.env } = {}) {
  const out = [];

  const explicit = env[PYTHON_ENV];
  if (explicit) out.push(explicit);

  if (repoRoot) {
    out.push(join(repoRoot, '.venv', 'bin', 'python')); // POSIX
    out.push(join(repoRoot, '.venv', 'Scripts', 'python.exe')); // Windows
  }

  const venv = env.VIRTUAL_ENV;
  if (venv) {
    out.push(join(venv, 'bin', 'python'));
    out.push(join(venv, 'Scripts', 'python.exe'));
  }

  const names = process.platform === 'win32'
    ? ['python.exe', 'python3.exe', 'python', 'python3']
    : ['python3', 'python'];
  for (const dir of (env.PATH || '').split(delimiter).filter(Boolean)) {
    for (const name of names) out.push(join(dir, name));
  }

  return out;
}

/**
 * 返回第一个存在的解释器路径；全部不可用返回 `null`。
 *
 * @param {{
 *   repoRoot?: string,
 *   env?: Record<string, string|undefined>,
 *   exists?: (p: string) => boolean,
 * }} opts `exists` 可注入，便于单测（默认 `fs.existsSync`）
 * @returns {string|null}
 */
export function resolvePython({ repoRoot, env = process.env, exists = existsSync } = {}) {
  for (const candidate of pythonCandidates({ repoRoot, env })) {
    try {
      if (exists(candidate)) return candidate;
    } catch {
      // 探测本身失败（权限/非法路径）视为「该项不可用」，继续下一个候选
    }
  }
  return null;
}

/**
 * 探测失败时的统一中文提示（调用方打印后应 `process.exit(1)`）。
 *
 * @param {string} scriptName 触发探测的脚本名，便于定位
 * @returns {string}
 */
export function missingPythonMessage(scriptName) {
  return (
    `[FAIL] ${scriptName}: 未找到可用的 Python 解释器。\n` +
    `  请设置环境变量 ${PYTHON_ENV} 指向 Python 可执行文件，` +
    '或在仓库根创建 .venv（POSIX: .venv/bin/python；Windows: .venv/Scripts/python.exe）。'
  );
}
