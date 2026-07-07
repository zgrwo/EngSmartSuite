# Benchmark: python-project-review v1

## Iteration 1 Results

| Metric | With Skill | Without Skill | Delta |
|--------|-----------|---------------|-------|
| **Pass Rate** | 100% (3/3) | 94.4% (2.83/3) | **+5.6%** |
| **Mean Tokens** | 66,043 | 53,167 | +24.2% |
| **Mean Duration** | 338.8s | 317.1s | +6.8% |

## Per-Eval Breakdown

### Eval 1: Data Pipeline Review
| Config | Pass | Tokens | Duration | Notes |
|--------|------|--------|----------|-------|
| With Skill | 6/6 | 68K | 217.8s | Found P1-01 n_affected=0 bug; structured findings.json |
| Without Skill | 6/6 | 77K | 526.9s | Found 9 issues but missed n_affected=0; no findings.json |

### Eval 2: Statistical Formula Verification
| Config | Pass | Tokens | Duration | Notes |
|--------|------|--------|----------|-------|
| With Skill | 5/5 | 63K | 409.9s | JT tie scoring gap found (P2); verified all 3 formulas |
| Without Skill | 5/5 | 49K | 270.6s | Similar quality; named tau_b imprecision |

### Eval 3: Architecture Compliance
| Config | Pass | Tokens | Duration | Notes |
|--------|------|--------|----------|-------|
| With Skill | 6/6 | 67K | 388.8s | **Found 4x P1 scipy re-import violations** |
| Without Skill | 5/6 | 33K | 153.7s | Missed P1 violations; thorough but surface-level |

## Key Insights

1. **With-skill finds hidden violations**: P1 scipy re-import violations in architecture review were caught by with-skill but completely missed by baseline
2. **With-skill produces structured output**: findings.json + report.md vs report.md only, enabling downstream tooling
3. **With-skill includes root cause analysis**: Every report explains why tests didn't catch the bugs
4. **Cost is modest**: +24% tokens, +7% time — well worth the thoroughness gain
5. **Baseline is faster for shallow checks**: Architecture baseline was 2.5x faster but missed P1 issues
