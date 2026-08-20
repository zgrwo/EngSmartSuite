#!/bin/sh
# ============================================================================
# validate-commit-msg.sh — Conventional Commits 提交信息校验（零依赖，POSIX sh）
#
# 用途（SSOT 校验规则）：
#   - 本地 git hook：scripts/git-hooks/commit-msg 调用本脚本
#   - CI：对 PR 内每个 commit 调用本脚本（见 ci.yml「提交规范检查」）
#
# 用法：
#   validate-commit-msg.sh <commit-message-file>   # 读文件（本地 hook 用法）
#   echo "<subject>" | validate-commit-msg.sh       # 读 stdin（CI 逐条用法）
#
# 规则：
#   - 格式：type(scope): subject  或  type: subject  或  type!: subject（破坏性变更）
#   - scope 可为空，允许中文/字母/数字/下划线/连字符/点（^[^) ]+）
#   - subject 非空，标题 ≤72 字符
#   - 允许类型：feat fix docs style refactor test chore build ci perf revert release
#   - 跳过：Merge / fixup! / Revert 前缀提交
#
# 退出码：0 = 通过；1 = 不符合（输出中文错误说明到 stderr）
# ============================================================================

# 读取提交信息（文件优先，否则 stdin）
if [ -n "$1" ] && [ -f "$1" ]; then
    msg=$(cat "$1")
else
    msg=$(cat)
fi

# 取第一行作为标题（subject）
subject=$(printf '%s\n' "$msg" | sed -n '1p')

# 跳过特例：merge / fixup! / revert
case "$subject" in
    "Merge "*) exit 0 ;;
    "merge "*) exit 0 ;;
    "fixup! "*) exit 0 ;;
    "Revert "*) exit 0 ;;
esac

# 匹配 Conventional Commits 格式（scope 允许中文与常见分隔符）
# 冒号后必须至少一个非空白字符（防 `fix(engine):  ` 纯空格 subject 通过）
if printf '%s' "$subject" | grep -Eq '^(feat|fix|docs|style|refactor|test|chore|build|ci|perf|revert|release)(\([^) ]+\))?(!)?: \S.*$'; then
    # 第二轮 #16：固定 UTF-8 locale 再按"字符"计数（wc -m 在非 UTF-8 locale 下
    # 对中文按字节计数，30 字中文标题会被误判为 ~90 超限）。C.UTF-8 在 glibc
    # 全系可用；不可用（如部分 macOS）时回退系统默认，不影响 ASCII 计数。
    export LC_ALL=C.UTF-8
    len=$(printf '%s' "$subject" | wc -m)
    if [ "$len" -gt 72 ]; then
        echo "❌ 提交标题过长（${len} 字符，上限 72）：${subject}" >&2
        exit 1
    fi
    exit 0
fi

echo "❌ 提交信息不符合 Conventional Commits 格式：" >&2
echo "   期望：type(scope): 描述  例如：fix(engine): 修复 anova 效应量计算" >&2
echo "   允许类型：feat fix docs style refactor test chore build ci perf revert release" >&2
echo "   实际：${subject}" >&2
exit 1
