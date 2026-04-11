#!/bin/bash
# code-wiki 安装脚本
# 将 code-wiki skill 和 agents 安装到指定项目
#
# 用法:
#   ./install.sh <目标项目路径>
#   ./install.sh /path/to/your/project
#
# 功能:
#   - 复制 skill 文件到 <项目>/.claude/skills/code-wiki/
#   - 复制 agent 文件到 <项目>/.claude/agents/
#   - 已存在的同名文件会被覆盖（会提示确认）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ========== 参数检查 ==========
if [ $# -lt 1 ]; then
    echo "用法: $0 <目标项目路径>"
    echo "示例: $0 /path/to/your/project"
    exit 1
fi

TARGET_PROJECT="$(cd "$1" && pwd)"

if [ ! -d "$TARGET_PROJECT" ]; then
    echo "错误: 目标路径不存在: $TARGET_PROJECT"
    exit 1
fi

# ========== 定义路径 ==========
SKILL_SRC="$SCRIPT_DIR/skill"
AGENTS_SRC="$SCRIPT_DIR/agents"

SKILL_DST="$TARGET_PROJECT/.claude/skills/code-wiki"
AGENTS_DST="$TARGET_PROJECT/.claude/agents"

# ========== 检查源文件 ==========
if [ ! -d "$SKILL_SRC" ] || [ ! -d "$AGENTS_SRC" ]; then
    echo "错误: 找不到 skill 或 agents 目录，请确认脚本位于 code-wiki 仓库根目录"
    exit 1
fi

# ========== 预检查：列出将被覆盖的文件 ==========
overwrite_files=()

# 检查 skill 文件
if [ -d "$SKILL_DST" ]; then
    while IFS= read -r -d '' file; do
        rel_path="${file#$SKILL_SRC/}"
        dst_file="$SKILL_DST/$rel_path"
        if [ -f "$dst_file" ]; then
            overwrite_files+=(".claude/skills/code-wiki/$rel_path")
        fi
    done < <(find "$SKILL_SRC" -type f -print0)
fi

# 检查 agent 文件
if [ -d "$AGENTS_DST" ]; then
    for file in "$AGENTS_SRC"/*.md; do
        [ -f "$file" ] || continue
        filename="$(basename "$file")"
        if [ -f "$AGENTS_DST/$filename" ]; then
            overwrite_files+=(".claude/agents/$filename")
        fi
    done
fi

# ========== 确认覆盖 ==========
if [ ${#overwrite_files[@]} -gt 0 ]; then
    echo "以下文件将被覆盖:"
    for f in "${overwrite_files[@]}"; do
        echo "  - $f"
    done
    echo ""
    read -r -p "是否继续？[y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "已取消"
        exit 0
    fi
fi

# ========== 创建目录 ==========
mkdir -p "$SKILL_DST/references"
mkdir -p "$SKILL_DST/scripts"
mkdir -p "$AGENTS_DST"

# ========== 复制 skill 文件 ==========
echo "正在安装 skill 文件..."

cp "$SKILL_SRC/SKILL.md" "$SKILL_DST/SKILL.md"
echo "  ✓ SKILL.md"

cp "$SKILL_SRC/references/"* "$SKILL_DST/references/"
echo "  ✓ references/ ($(ls "$SKILL_SRC/references/" | wc -l | tr -d ' ') 个文件)"

cp "$SKILL_SRC/scripts/scan.py" "$SKILL_DST/scripts/scan.py"
echo "  ✓ scripts/scan.py"

# ========== 复制 agent 文件 ==========
echo "正在安装 agent 文件..."

agent_count=0
for file in "$AGENTS_SRC"/*.md; do
    [ -f "$file" ] || continue
    cp "$file" "$AGENTS_DST/"
    echo "  ✓ $(basename "$file")"
    ((agent_count++))
done

# ========== 完成 ==========
echo ""
echo "安装完成！"
echo "  目标项目: $TARGET_PROJECT"
echo "  Skill: .claude/skills/code-wiki/"
echo "  Agents: .claude/agents/ ($agent_count 个)"
echo ""
echo "在目标项目中使用 /code-wiki 即可启动"
