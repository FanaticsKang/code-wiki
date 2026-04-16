#!/bin/bash
# code-wiki 安装脚本
# 将 skills/ 下的 skill 和 agents/ 安装到指定项目
#
# 用法:
#   ./install.sh <目标项目路径>              # 安装核心 skills
#   ./install.sh --full <目标项目路径>       # 安装全部 skills（含可选）
#
# 功能:
#   - 默认只安装核心 skill 到 <项目>/.claude/skills/
#   - --full 模式安装全部 skill（含可选）
#   - 复制 agent 文件到 <项目>/.claude/agents/
#   - 已存在的同名文件会被覆盖（会提示确认）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ========== 核心 Skill 列表（默认安装） ==========
CORE_SKILLS=("code-wiki" "module-test-gen")

# ========== skill 过滤函数 ==========
is_installable() {
    local skill_name="$1"
    if [ "$FULL_MODE" = true ]; then
        return 0  # --full 安装全部
    fi
    for core in "${CORE_SKILLS[@]}"; do
        [ "$skill_name" = "$core" ] && return 0
    done
    return 1  # 非核心 skill，默认跳过
}

# ========== 参数解析 ==========
FULL_MODE=false
TARGET_PROJECT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --full) FULL_MODE=true; shift ;;
        -h|--help)
            echo "用法: $0 [--full] <目标项目路径>"
            echo ""
            echo "选项:"
            echo "  --full    安装全部 skills（含可选 skill）"
            echo ""
            echo "默认只安装核心 skills: ${CORE_SKILLS[*]}"
            echo "示例: $0 /path/to/your/project"
            exit 0
            ;;
        *)
            TARGET_PROJECT="$1"
            shift
            ;;
    esac
done

# ========== 参数检查 ==========
if [ -z "$TARGET_PROJECT" ]; then
    echo "用法: $0 [--full] <目标项目路径>"
    echo "示例: $0 /path/to/your/project"
    echo "      $0 --full /path/to/your/project"
    exit 1
fi

if [ ! -d "$TARGET_PROJECT" ]; then
    echo "错误: 目标路径不存在: $TARGET_PROJECT"
    exit 1
fi

TARGET_PROJECT="$(cd "$TARGET_PROJECT" && pwd)"

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

# ========== 显示安装模式 ==========
if [ "$FULL_MODE" = true ]; then
    echo "安装模式: 完整安装（全部 skills）"
else
    echo "安装模式: 核心安装 (${CORE_SKILLS[*]})"
    echo "  提示: 使用 --full 安装全部 skills（含可选）"
fi
echo ""

# ========== 预检查：列出将被覆盖的文件 ==========
overwrite_files=()
skipped_skills=()

# 检查所有 skill 文件
for skill_dir in "$SKILLS_SRC"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name="$(basename "$skill_dir")"

    if ! is_installable "$skill_name"; then
        skipped_skills+=("$skill_name")
        continue
    fi

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
echo "正在安装 skills..."

for skill_dir in "$SKILLS_SRC"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name="$(basename "$skill_dir")"

    if ! is_installable "$skill_name"; then
        continue
    fi

    skill_dst="$SKILLS_DST/$skill_name"

    mkdir -p "$skill_dst"

    # 递归复制 skill 目录下的所有内容
    cp -R "$skill_dir." "$skill_dst/"

    file_count=$(find "$skill_dst" -type f | wc -l | tr -d ' ')
    echo "  ✓ skills/$skill_name/ ($file_count 个文件)"
    ((skill_count++))
done

echo "已安装 $skill_count 个 skill"

# 显示跳过信息
if [ ${#skipped_skills[@]} -gt 0 ]; then
    echo "跳过可选 skills: ${skipped_skills[*]}"
    echo "  使用 --full 可安装这些 skills"
fi

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
if [ "$FULL_MODE" = true ]; then
    echo "  /unit-test-gen init | generate | run | auto"
    echo "  /paper-code-deepdive"
fi
