# 工具与脚本坑位清单（Windows / PowerShell / git / CI）

> 从 VibeCodingTemplate 多个子项目实际踩坑提炼的跨项目工具级陷阱，按本仓情况裁剪并补充套件自身历史。
> 修改 `scripts/`、运行终端命令、处理 git/CI 操作前必读。项目专属坑位（如统计语义）在 `agents.md`「历史经验」，本文件只收工具链问题。

## PowerShell / Windows 陷阱

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 1 | **PowerShell 5.1 处理 UTF-8 文件乱码**（默认 ANSI 读取/写入）；含中文注释的 `.ps1` 文件若**无 BOM**，解析器按 ANSI 读注释 → 语法解析失败 | 读写文件显式指定编码：`Get-Content -Encoding UTF8`、`Set-Content -Encoding UTF8`；含中文的 `.ps1` 必须存为 UTF-8 with BOM；命令行查看中文文档乱码多为显示编码问题，用 `Get-Content -Encoding UTF8` 复核 |
| 2 | **`&&` 语句分隔符**（PowerShell 5.1 不支持） | 用 `;` 分隔命令，或 `if ($LASTEXITCODE -eq 0)` 判断 |
| 3 | **`robocopy` 退出码 1 表示"复制成功"**（非 0 即失败的错误假设） | `robocopy` 退出码 <8 均算成功；检查 `$LASTEXITCODE -lt 8` |
| 4 | **`foreach` 语法缺 `in` 关键字**（`foreach $x $list`）→ 语法错误 | `foreach ($x in $list) { ... }` |

## git 陷阱

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 5 | **`git add` 无法暂存未跟踪文件的"删除"**（文件从未提交过，删除后无 stage 记录） | 删除未跟踪文件无需 git 操作；提交过则用 `git rm` 或 `git add -A` |
| 6 | **`git fetch --unshallow` 仅适用于浅克隆仓库** → 普通仓库报错 | 先 `git rev-parse --is-shallow-repository` 确认 |
| 7 | **`git diff --name-only` 不含未跟踪新文件** → 增量工具漏掉新建脚本/测试 | 合并 `git ls-files --others --exclude-standard`（见 run_affected_tests.py） |
| 8 | **CI checkout 默认浅克隆（fetch-depth=1）** → 提交规范检查 `base..HEAD` 无历史可用 | 需完整历史的 job 显式 `fetch-depth: 0` |

## CI / YAML 陷阱

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 9 | **YAML block scalar 内多行缩进破坏解析**（内联 python 代码块） | 单行 `python -c "..."`，避免多行缩进；复杂逻辑放脚本文件 |
| 10 | **grep BRE 转义 `\{` 依赖版本宽容行为**（新版 GNU grep 3.11 对 `\{` 后非数字报 `Invalid content` exit 2） | 固定串匹配用 `grep -F`；关键检测分支**不要 `2>/dev/null` 吞错误**（grep 出错应暴露在日志） |
| 11 | **pip-audit 审计整个环境 → runner 预装系统包几十个 CVE 假阳性** | 定向审计项目声明依赖：从 pyproject.toml 提取 dependencies + dev extras 后 `pip_audit -r deps.txt`；先安装项目依赖再审计（否则审计的是 runner 环境 = no-op） |
| 12 | **自校验正则误伤 docstring/注释中的教学文字**（如本文档提到「裸 `except:`」被扫描器命中） | 扫描跳过注释/docstring 行；规则与实现同源（verify_docs.py 语义向量），不用裸 grep 自检 |
| 13 | **测试文件命名不匹配框架默认 glob** → 测试永不运行、CI 静默通过 | 后缀用框架默认匹配（pytest `test_*.py`）；辅助验证模块（`_diff_cli_web.py`）不被收集时显式说明其调用方 |

## 脚本/验证工具陷阱

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 14 | **`Path.rglob` 在文件上不迭代** → 扫描脚本对单文件路径静默输出"无发现"（门禁说谎） | 扫描入口先校验 `scope.is_dir()`，文件路径显式报错 |
| 15 | **`check_undeclared` 只查根级** → 子目录新增 `rules/*.md` 等静默通过 | 对 SSOT 关键子目录（rules/skills）逐文件比对目录树声明（verify_docs.py --strict） |
| 16 | **类型注解安全判定用子串匹配**（`"list" in hint.lower()`）→ `Optional[list[float]]` 被误判 | 解析注解 AST 取顶层类型构造器，`X \| None` 联合视为 Optional |
| 17 | **工具命名映射未归一化连字符/下划线**（`validate-commit-msg.sh` vs `test_validate_commit_msg.py` 子串匹配失效）→ 门禁谎报"缺测" | 比较前统一分隔符：`stem.replace('-', '_')` 再子串匹配（见 run_affected_tests.py） |
| 18 | **ruff per-file ignore 无理由注释**（来源：本仓 pyproject.toml 历史教训）→ 后人 copy-paste 忽略规则，无上下文 | 每条 per-file-ignores/noqa 必须带中文理由注释；新增规则类别需先确认非"覆盖问题"而是"约定豁免" |
| 19 | **配置流断裂（声明→解析→传递→读取→使用任一环断开）** → 参数在配置中声明但链路某节点静默失效 | 新增注册点后立即用一致性检查断言多注册表键集一致（CI consistency job：TASK_REGISTRY == DEFAULT_PARAMS == TASK_LABELS == TASK_GROUPS） |
| 20 | **验证脚本 `if __name__ == "__main__"` 守卫被绕过**（`spec_from_file_location` 加载时 `__name__` 恒为模块 stem）→ 校验逻辑不执行仍 exit 0（门禁说谎） | 测试用入口断言（`main()` 直接调用）；CI 直接跑脚本而非 import |

## 套件历史踩坑（从 agents.md「历史经验」固化）

| # | 陷阱 | 正确做法 |
|---|------|----------|
| 21 | **winreg ImportError**（Linux 上未捕获 Windows API） | `import winreg` 包 `try/except ImportError`，或延迟到 Windows 分支 |
| 22 | **matplotlib 后端冲突**（CLI 模式下 pyplot 提前导入 → Agg 后端报错） | CLI 入口在导入 pyplot 前 `matplotlib.use("Agg")`；engine/__init__.py 集中配置（见 pyproject.toml per-file-ignores 注释） |
| 23 | **GBK 控制台输出乱码**（Windows 终端默认 GBK，UTF-8 中文输出乱码） | 脚本入口 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`（本仓 scripts/ 统一约定） |
| 24 | **pytest-current junction 残留**（Windows 上嵌套 pytest 会话的 `pytest-of-<user>/pytest-current` junction 清理阶段 PermissionError → sessionfinish 报错、进程退出码 1，verify_all/CI 误判失败） | 嵌套 pytest 与 verify_all 调用显式加 `--basetemp` 隔离；或清理 `%TEMP%\pytest-of-zgrwo` 残留目录 |

## 提交前自查

```bash
# 检查脚本中是否出现高频坑位
grep -rn "except:" src/ scripts/ --include="*.py" || echo "OK（无裸 except）"
python scripts/verify_docs.py --strict   # 文档断链/目录树/语义/版本漂移
python scripts/test_quality_guard.py     # 测试弱断言/缺测/命名
```

## 维护规则

- 新踩坑并验证修复后，**立即追加到本表**（附真实案例与正确做法）
- 语言级陷阱只在 `skills/smartsuite-dev.md` 维护（本表只留工具链问题，禁止双写）
- 项目专属坑位（统计语义/业务规则）写入 `agents.md`「历史经验」，不放本文件
