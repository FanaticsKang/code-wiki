#!/bin/bash
# code-wiki 安装脚本
# 将 skills/ 下的所有 skill 和 agents/ 安装到指定项目
#
# 用法:
#   ./install.sh <目标项目路径>
#   ./install.sh /path/to/your/project
#
# 功能:
#   - 复制 skills/ 下所有 skill 到 <项目>/.claude/skills/
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
SKILLS_SRC="$SCRIPT_DIR/skills"
AGENTS_SRC="$SCRIPT_DIR/agents"

SKILLS_DST="$TARGET_PROJECT/.claude/skills"
AGENTS_DST="$TARGET_PROJECT/.claude/agents"

# ========== 检查源文件 ==========
if [ ! -d "$SKILLS_SRC" ]; then
    echo "错误: 找不到 skills 目录，请确认脚本位于仓库根目录"
    exit 1
fi

# ========== 预检查：列出将被覆盖的文件 ==========
overwrite_files=()

# 检查所有 skill 文件
for skill_dir in "$SKILLS_SRC"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name="$(basename "$skill_dir")"
    skill_dst="$SKILLS_DST/$skill_name"

    if [ -d "$skill_dst" ]; then
        while IFS= read -r -d '' file; do
            rel_path="${file#$skill_dir}"
            dst_file="$skill_dst/$rel_path"
            if [ -f "$dst_file" ]; then
                overwrite_files+=(".claude/skills/$skill_name/$rel_path")
            fi
        done < <(find "$skill_dir" -type f -print0)
    fi
done

# 检查 agent 文件
if [ -d "$AGENTS_SRC" ] && [ -d "$AGENTS_DST" ]; then
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
mkdir -p "$SKILLS_DST"
mkdir -p "$AGENTS_DST"

# ========== 复制 skill 文件 ==========
skill_count=0
for skill_dir in "$SKILLS_SRC"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name="$(basename "$skill_dir")"
    skill_dst="$SKILLS_DST/$skill_name"

    mkdir -p "$skill_dst"

    # 递归复制 skill 目录下的所有内容
    cp -R "$skill_dir." "$skill_dst/"

    file_count=$(find "$skill_dst" -type f | wc -l | tr -d ' ')
    echo "  ✓ skills/$skill_name/ ($file_count 个文件)"
    ((skill_count++))
done

echo "已安装 $skill_count 个 skill"

# ========== 复制 agent 文件 ==========
if [ -d "$AGENTS_SRC" ]; then
    echo "正在安装 agent 文件..."

    agent_count=0
    for file in "$AGENTS_SRC"/*.md; do
        [ -f "$file" ] || continue
        cp "$file" "$AGENTS_DST/"
        echo "  ✓ $(basename "$file")"
        ((agent_count++))
    done

    echo "已安装 $agent_count 个 agent"
fi

# ========== 完成 ==========
echo ""
echo "安装完成！"
echo "  目标项目: $TARGET_PROJECT"
echo "  Skills:  .claude/skills/ ($skill_count 个)"
echo "  Agents:  .claude/agents/"
echo ""
echo "可用命令："
echo "  /code-wiki init | scan | query | lint"
echo "  /module-test-gen init | generate | run"
