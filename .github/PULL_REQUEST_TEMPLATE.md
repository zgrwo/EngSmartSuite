# PR 描述

## 变更类型

- [ ] Bug 修复（数值/逻辑/崩溃）
- [ ] 新功能（新方法/新参数）
- [ ] 重构（不改变行为）
- [ ] 文档更新
- [ ] CI/工具链

## 变更内容

<!-- 简述做了什么、为什么 -->

## 测试验证

```bash
# 粘贴测试输出
pytest tests/ -x -q
ruff check src/smartsuite/
```

## 检查清单

- [ ] 11 步注册链完成（如新增方法）
- [ ] 效应量 + 95% CI 已报告（如统计检验）
- [ ] 中文工艺语言 summary
- [ ] 无裸 `except:` 或 `except Exception:` 不记录日志
- [ ] `ruff check` 零错误
- [ ] 全量测试通过
- [ ] api-reference.md 已同步（如接口变更）
