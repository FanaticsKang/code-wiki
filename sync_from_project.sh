#!/bin/bash
# code-wiki 反向同步脚本
# 从指定项目中已安装的 code-wiki 文件更新本仓库（主仓库）
#
# 用法:
#   ./sync_from_project.sh <项目路径>
#   ./sync_from_project.sh /path/to/project_with_code_wiki
#
# 功能:
#   - 从 <项目>/.claude/skills/code-wiki/ 复制回 skill 文件
#   - 从 <项目>/.claude/agents/ 复制回 code-wiki 相关 agent 文件
#   - 已存在的文件会被覆盖（会提示确认）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ========== 参数检查 ==========
if [ $# -lt 1 ]; then
    echo "用法: $0 <项目路径>"
    echo "示例: $0 /path/to/project_with_code_wiki"
    exit 1
fi

SOURCE_PROJECT="$(cd "$1" && pwd)"

if [ ! -d "$SOURCE_PROJECT" ]; then
    echo "错误: 源项目路径不存在: $SOURCE_PROJECT"
    exit 1
fi

# ========== 定义路径 ==========
SKILL_SRC="$SOURCE_PROJECT/.claude/skills/code-wiki"
AGENTS_SRC="$SOURCE_PROJECT/.claude/agents"

SKILL_DST="$SCRIPT_DIR/skill"
AGENTS_DST="$SCRIPT_DIR/agents"

# ========== 检查源项目是否有 code-wiki ==========
if [ ! -d "$SKILL_SRC" ]; then
    echo "错误: 目标项目中未找到 code-wiki skill: $SKILL_SRC"
    exit 1
fi

if [ ! -f "$SKILL_SRC/SKILL.md" ]; then
    echo "错误: 目标项目中未找到 SKILL.md: $SKILL_SRC/SKILL.md"
    exit 1
fi

# ========== 显示 diff 摘要 ==========
echo "比较文件差异..."

changed_files=()
new_files=()

# 比较 skill 文件
while IFS= read -r -d '' file; do
    rel_path="${file#$SKILL_SRC/}"
    dst_file="$SKILL_DST/$rel_path"
    if [ -f "$dst_file" ]; then
        if ! diff -q "$file" "$dst_file" > /dev/null 2>&1; then
            changed_files+=("skill/$rel_path")
        fi
    else
        new_files+=("skill/$rel_path")
    fi
done < <(find "$SKILL_SRC" -type f -not -name '__pycache__' -not -path '*__pycache__*' -print0)

# 比较 agent 文件
for file in "$AGENTS_SRC"/code-wiki-*.md; do
    [ -f "$file" ] || continue
    filename="$(basename "$file")"
    dst_file="$AGENTS_DST/$filename"
    if [ -f "$dst_file" ]; then
        if ! diff -q "$file" "$dst_file" > /dev/null 2>&1; then
            changed_files+=("agents/$filename")
        fi
    else
        new_files+=("agents/$filename")
    fi
done

# ========== 显示结果 ==========
if [ ${#changed_files[@]} -eq 0 ] && [ ${#new_files[@]} -eq 0 ]; then
    echo "所有文件已是最新，无需同步。"
    exit 0
fi

echo ""
if [ ${#changed_files[@]} -gt 0 ]; then
    echo "已修改的文件 (${#changed_files[@]}):"
    for f in "${changed_files[@]}"; do
        echo "  ~ $f"
    done
fi

if [ ${#new_files[@]} -gt 0 ]; then
    echo "新增的文件 (${#new_files[@]}):"
    for f in "${new_files[@]}"; do
        echo "  + $f"
    done
fi

echo ""
read -r -p "是否同步以上文件到主仓库？[y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# ========== 创建目录 ==========
mkdir -p "$SKILL_DST/references"
mkdir -p "$SKILL_DST/scripts"
mkdir -p "$AGENTS_DST"

# ========== 同步 skill 文件 ==========
echo "正在同步 skill 文件..."

cp "$SKILL_SRC/SKILL.md" "$SKILL_DST/SKILL.md"

if ls "$SKILL_SRC/references/"* > /dev/null 2>&1; then
    cp "$SKILL_SRC/references/"* "$SKILL_DST/references/"
fi

if [ -f "$SKILL_SRC/scripts/scan.py" ]; then
    cp "$SKILL_SRC/scripts/scan.py" "$SKILL_DST/scripts/scan.py"
fi

echo "  ✓ skill 文件已同步"

# ========== 同步 agent 文件 ==========
echo "正在同步 agent 文件..."

agent_count=0
for file in "$AGENTS_SRC"/code-wiki-*.md; do
    [ -f "$file" ] || continue
    cp "$file" "$AGENTS_DST/"
    echo "  ✓ $(basename "$file")"
    ((agent_count++))
done

if [ "$agent_count" -eq 0 ]; then
    echo "  (未找到 code-wiki agent 文件)"
fi

# ========== 完成 ==========
echo ""
echo "同步完成！"
echo "  源项目: $SOURCE_PROJECT"
echo "  更新文件: $((${#changed_files[@]} + ${#new_files[@]})) 个"
