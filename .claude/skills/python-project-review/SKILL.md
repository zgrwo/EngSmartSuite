---
name: python-project-review
description: >-
  Comprehensive Python project code review with convergence loop and toolchain
  integration. Use whenever the user asks for a "project review", "code audit",
  "全面审查", "深度审查", "代码审计", or any variant of "review this codebase /
  this project / all the code". Triggers on requests beyond a single file or PR:
  "check the whole project for bugs", "audit the codebase", "is this project
  solid?", "帮我审查这个 Python 项目的代码质量". Orchestrates multi-angle
  parallel finders, adversarial verification, root-cause tracing, and optional
  fix→re-review convergence loop. Auto-runs ruff, vulture, pip-audit as baseline.
---

# Python Project Review — 多维度并行代码审查 + 收敛循环

Systematic, multi-angle audit of a Python codebase with three community-proven
enhancements: **automated toolchain scan** (ruff/vulture/pip-audit),
**adversarial verification** (single-vote confirm/refute), and **convergence
loop** (fix → re-review until no new findings).

## When to use

Trigger on requests about the **project as a whole**. Handles full-project
sweeps and focused deep-dives into specific subsystems.

Skip when the user asks for `/code-review` (diff-only) or `/review` (GitHub PR).

## Review Flow

```
Phase 0 ──→ Toolchain scan (ruff / vulture / pip-audit)
         │
Phase 1 ──→ 7-angle parallel finders (Agent × 7)
         │
Phase 2 ──→ Adversarial verification (1 verifier per finding)
         │
Phase 3 ──→ Root-cause trace (why tests missed it)
         │
Phase 4 ──→ Synthesize ranked report
         │
Phase 5 ──→ Fix → re-review convergence loop (optional, user-directed)
         ↑
         └── repeat until 2 consecutive passes find nothing new
```

---

### Phase 0 — Automated toolchain scan

Run these tools BEFORE the human review angles. Results feed into Phase 1 as
baseline data, so finders don't waste time on machine-checkable issues.

**0a. ruff — lint + style**
```bash
ruff check <source-dir>/ --output-format concise 2>&1
```
- Parse the output. Categorize violations by rule (F=pyflakes, E=pycodestyle,
  I=isort, N=pep8-naming, B=bugbear, UP=pyupgrade).
- Flag any **F** (pyflakes) violations as P2 candidates — they indicate
  undefined names, unused imports that might signal dead code paths.
- Note the count of fixable vs. manual issues.

**0b. vulture — dead code detection**
```bash
vulture <source-dir>/ --min-confidence 70 2>&1
```
- Vulture finds unused functions, classes, variables.
- Cross-reference with grep: a symbol vulture flags might be called via
  `getattr`, `__all__` exports, or plugin systems. Verify before reporting.
- Confirmed dead code → P3 finding. Dead code that imports heavy deps → P2.

**0c. pip-audit — dependency vulnerabilities (if project has requirements)**
```bash
pip-audit --requirement requirements.txt 2>&1 || true
```
- Report any HIGH/CRITICAL vulnerabilities as P1 security findings.
- MODERATE → P2. LOW → note in report but don't block.
- If `pip-audit` is not installed, skip with a note: "pip-audit not available,
  dependency scan skipped".

---

### Phase 1 — Parallel finders (7 angles + toolchain results)

Launch **all 7 finder agents in a single turn**. Each returns ≤6 candidate
findings as JSON `[{file, line, summary, failure_scenario}]`. Include the
Phase 0 toolchain results as context for all finders.

| Angle | Agent focus | Reads |
|-------|------------|-------|
| **A. Correctness** | Line-by-line scan: wrong conditions, off-by-one, null/NaN deref, missing guards, inverted logic, copy-paste errors, swallowed exceptions | All source files in scope |
| **B. Invariants** | For every guard/validation/check, name the invariant. Search for re-establishment elsewhere. Flag gaps where a guard was removed but not replaced. | Source + test files |
| **C. Cross-file** | For every public function, find all callers. Check: new preconditions, changed return shape, new exceptions, timing/ordering assumptions | Source files |
| **D. Reuse/Simplify** | Flag reimplemented utilities, copy-paste with drift, dead code (zero callers), magic numbers repeated across files. Cross-reference with vulture results. | Source + utils |
| **E. Efficiency** | Repeated I/O, double-computation on hot paths, unclosed resources, large objects in closures, blocking calls in startup | Source files |
| **F. Altitude** | Is each fix at the right layer? Special cases on shared infra → generalize. Band-aids that should be deeper. | Source files |
| **G. Conventions** | Read CLAUDE.md. Check: layer boundaries, import rules, error language, return type contracts, export lists. Cross-reference ruff violations. | CLAUDE.md + source |

---

### Phase 2 — Verify (adversarial single-vote)

1. Deduplicate near-duplicates (same defect, same location → keep one).
2. For each candidate, spawn **one verifier agent**. The verifier reads the
   actual source lines, traces the logic, and returns:
   - **CONFIRMED** — bug is real and reproducible from the code
   - **PLAUSIBLE** — could happen but depends on rare-but-realistic state
   - **REFUTED** — impossible, already handled, or factually wrong

Keep CONFIRMED and PLAUSIBLE. Drop REFUTED.

---

### Phase 3 — Root-cause trace

For every confirmed finding, answer: **"Why did the existing test suite not
catch this?"** Common patterns:

| Pattern | Signal |
|---------|--------|
| Edge case not in test data | Single-quote column names, NaN-only columns, empty DataFrames |
| Type bridge gap | JS `""` vs Python `None`, CLI vs Web path divergence |
| Path not in CI | Experimental GUI, optional dependency code paths |
| Smoke-test-only coverage | Test checks `status=="ok"` but not output values |
| Mocked dependency | Mock hides real exception types, type mismatches |
| Implicit assumption | Tests assume column names are ASCII, data has ≥N rows |

---

### Phase 4 — Synthesize and report

```
## 综合代码审查报告 — [Project Name]

**审查范围**: [Scope]
**审查方法**: Toolchain scan + 7-angle parallel review + adversarial verification
**审查日期**: [Date]

### 工具链扫描结果
- ruff: [N errors, M warnings]
- vulture: [N dead symbols found, M confirmed]
- pip-audit: [N vulnerabilities (H/M/L)]

### 综合评价: [Grade]
[One paragraph: what's good, what's concerning, overall trend]

### Top Findings (by severity)
#### [P0/P1] Finding title — [file:line]
**故障场景**: [Concrete inputs → wrong output / crash]
**根因**: [Why the code is wrong]
**测试为何未捕获**: [Pattern from Phase 3]

### 一句话结论
[One sentence in Chinese]
```

Rank findings most-severe first. If >10 survive verification, keep the top 10.

---

### Phase 5 — Convergence loop (user-directed)

After the report is delivered and the user fixes issues, ask:

> "我已修复了 [N] 个问题。要我重新审查确认没有引入新问题吗？"

If the user says yes:

1. Re-run **only phases 1-4** (skip toolchain scan unless deps changed).
2. Compare new findings against the previous report:
   - **RESOLVED** — finding no longer present → mark as fixed
   - **NEW** — finding wasn't in previous report → potential regression
   - **PERSISTENT** — finding still present → escalate (P2→P1, P3→P2)
3. If the re-review finds **zero NEW findings**, the loop converges. Report:
   "✅ 审查收敛 — 无新增问题，所有已知问题已修复或豁免。"
4. If new findings appear, deliver them and offer another round.

**Convergence budget**: maximum 3 rounds. If still finding issues after round 3,
report the remaining items as "建议分批处理" and stop.

---

## Severity rubric

| Level | Criteria |
|-------|----------|
| **P0** | Data corruption, security vulnerability, crash on common input, wrong statistical result with no warning |
| **P1** | Crash on edge-case input, silent wrong behavior, feature completely broken |
| **P2** | Misleading error message, performance regression, inconsistent behavior across paths |
| **P3** | Dead code, minor duplication, style/convention violation, missing optimization |

---

## Project-specific conventions (Chinese Python projects)

1. **Error messages use Chinese** (工艺术语) — no raw Python tracebacks exposed
2. **CLAUDE.md** is the authoritative source — verify consistency with actual code
3. **Layer boundaries** — web/ must not import engine/, engine/ zero UI deps
4. **Data pipeline** — validate() messages match preprocess() behavior
5. **Test strategy** — correctness + invariants + fuzz + differential, not just smoke

---

## Bundled Resources

### `references/benchmark-report.md`
Benchmark: with-skill vs without-skill. +5.6% pass rate, +24% tokens.

### `references/benchmark.json`
Machine-readable benchmark data.

### `references/evals.json`
3 test cases used for evaluation.

### `references/eval-reports/`
6 review reports (3 with-skill + 3 baseline) from SmartSuite evaluation run.
