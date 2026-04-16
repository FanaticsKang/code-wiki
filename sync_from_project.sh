#!/bin/bash
# code-wiki 反向同步脚本
# 从指定项目中已安装的 skill/agent 文件更新本仓库（主仓库）
#
# 用法:
#   ./sync_from_project.sh <项目路径>
#   ./sync_from_project.sh /path/to/project_with_code_wiki
#
# 功能:
#   - 从 <项目>/.claude/skills/ 复制回所有 skill 文件
#   - 从 <项目>/.claude/agents/ 复制回 agent 文件
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
SKILLS_SRC="$SOURCE_PROJECT/.claude/skills"
AGENTS_SRC="$SOURCE_PROJECT/.claude/agents"

SKILLS_DST="$SCRIPT_DIR/skills"
AGENTS_DST="$SCRIPT_DIR/agents"

# ========== 检查源项目是否有已安装的 skill ==========
if [ ! -d "$SKILLS_SRC" ]; then
    echo "错误: 目标项目中未找到 skills 目录: $SKILLS_SRC"
    exit 1
fi

# ========== 显示 diff 摘要 ==========
echo "比较文件差异..."

changed_files=()
new_files=()

# 比较所有 skill 文件
for skill_dir in "$SKILLS_DST"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name="$(basename "$skill_dir")"
    skill_src="$SKILLS_SRC/$skill_name"

    if [ ! -d "$skill_src" ]; then
        continue
    fi

    while IFS= read -r -d '' file; do
        rel_path="${file#$skill_src/}"
        dst_file="$skill_dir$rel_path"
        if [ -f "$dst_file" ]; then
            if ! diff -q "$file" "$dst_file" > /dev/null 2>&1; then
                changed_files+=("skills/$skill_name/$rel_path")
            fi
        else
            new_files+=("skills/$skill_name/$rel_path")
        fi
    done < <(find "$skill_src" -type f -not -name '__pycache__' -not -path '*__pycache__*' -print0)
done

# 比较 agent 文件
if [ -d "$AGENTS_SRC" ]; then
    for file in "$AGENTS_SRC"/*.md; do
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
fi

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

# ========== 同步 skill 文件 ==========
echo "正在同步 skill 文件..."

for skill_dir in "$SKILLS_DST"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name="$(basename "$skill_dir")"
    skill_src="$SKILLS_SRC/$skill_name"

    if [ ! -d "$skill_src" ]; then
        continue
    fi

    # 确保目标子目录存在
    mkdir -p "$skill_dir"

    # 同步文件
    while IFS= read -r -d '' file; do
        rel_path="${file#$skill_src/}"
        dst_file="$skill_dir$rel_path"
        mkdir -p "$(dirname "$dst_file")"
        cp "$file" "$dst_file"
    done < <(find "$skill_src" -type f -not -name '__pycache__' -not -path '*__pycache__*' -print0)

    echo "  ✓ skills/$skill_name/"
done

# ========== 同步 agent 文件 ==========
echo "正在同步 agent 文件..."

mkdir -p "$AGENTS_DST"

agent_count=0
if [ -d "$AGENTS_SRC" ]; then
    for file in "$AGENTS_SRC"/*.md; do
        [ -f "$file" ] || continue
        cp "$file" "$AGENTS_DST/"
        echo "  ✓ $(basename "$file")"
        ((agent_count++))
    done
fi

if [ "$agent_count" -eq 0 ]; then
    echo "  (未找到 agent 文件)"
fi

# ========== 完成 ==========
echo ""
echo "同步完成！"
echo "  源项目: $SOURCE_PROJECT"
echo "  更新文件: $((${#changed_files[@]} + ${#new_files[@]})) 个"
