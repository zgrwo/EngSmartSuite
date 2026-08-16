# 安全政策

> **Language note / 语言说明**: This document is maintained in Chinese by design
> (primary audience). For English vulnerability reporting, use GitHub's
> **Private Vulnerability Reporting** tab (language-neutral).
> 本文档按设计仅提供中文版（主要受众为中文用户）；漏洞上报流程见上方英文说明。

## 支持的版本

| 版本 | 支持状态 |
|------|----------|
| 最新 release | ✅ 积极支持 |
| 更早版本 | ❌ 不再支持，建议升级 |

## 报告漏洞

请**不要**公开披露安全漏洞。通过以下方式私密报告：

1. **首选**：在仓库的 Security 标签页创建私有漏洞报告（Private Vulnerability Reporting）

请包含：

- 受影响的版本
- 漏洞描述与复现步骤
- 影响评估（是否可被远程利用 / 是否泄露数据）

## 响应时间表

| 阶段 | 目标时限 |
|------|----------|
| 初步确认（回复报告人） | 2 个工作日 |
| 漏洞评估与分诊 | 5 个工作日 |
| 严重漏洞（可远程利用 / 数据泄露）修复发布 | 14 个工作日 |
| 中低危漏洞修复发布 | 随下一常规版本 |

> 以上为目标值；若无法按期完成，会主动向报告人同步进展。

## 安全承诺

- 所有安全相关修复优先处理，不等待常规发版周期
- 修复后会在 CHANGELOG.md 中标注，并建议用户尽快升级
- 本项目遵循 [agents.md](agents.md) 的安全红线：无裸异常捕获不记录日志、错误信息不暴露
  traceback、无敏感信息泄漏（密钥不入库，见 .gitignore），以及哨兵契约的「静默传播阻断」
  （见 [rules/sentinel-contract.md](rules/sentinel-contract.md)）
- 依赖安全由 CI 守护：`security.yml` 工作流定期执行 CodeQL 静态扫描与 pip-audit 依赖漏洞审计

## 已知安全设计

> 本仓库为本地 Web 分析工具：Flask 开发服务器默认仅绑定 127.0.0.1（见 web/app.py），
> 不面向公网部署；依赖安全基线由 dependabot + pip-audit 自动维护。
