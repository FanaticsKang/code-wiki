# 查询与健康检查（workflow-query-lint）

扫描是主要工作，但 wiki 建好之后还有两种常见操作：**基于 wiki 回答用户问题**（query）和**定期健康检查**（lint）。

## Query：基于 wiki 回答问题

用户建好 wiki 之后（或扫描到一半），会开始问各种问题：
- "这个项目的权限检查在哪里做的？"
- "`UserService.create` 被谁调用？"
- "如果我想改数据库 schema，要动哪些文件？"
- "这个项目有几种后台任务？"

**核心原则**：先查 wiki，再查源码，最后回填。

### 步骤

**1. 先读 `index.md`**

不要一上来就 `grep` 源码。`index.md` 是 wiki 的目录，它告诉你有哪些页面可能相关。如果 wiki 已经有几十页了，先扫一遍索引再决定读哪几页，比乱 grep 源码快得多。

**2. 读相关的 modules/concepts/architecture 页**

基于索引挑出 2-5 个最相关的页面读完。通常答案已经在里面了，或者起码能定位到正确的代码位置。

**3. 如果 wiki 不够，再去读源码**

这时候你已经有了精确的位置（"权限检查应该在 `api/middleware/auth.py`"），去源码里确认细节。用 `rg` / `grep` 做精确搜索，不要漫无目的地 view 目录。

**4. 回答用户**

- **引用 wiki 页**：用相对路径链接到你参考的页面。
- **引用源码**：用 `src/path/file.py:行号范围` 的格式。
- **区分"wiki 里写过的"和"新发现的"**：如果答案是新发现的（wiki 里还没写），明确告诉用户"这是我刚刚读源码发现的"。

**5. 回填**

这是关键的一步，**不要跳过**。如果用户的问题揭示了 wiki 里没有的信息，把答案沉淀回 wiki：

- 如果是一个"新概念"级别的发现 → 新建或更新 `concepts/<概念>.md`
- 如果是一个"模块职责"级别的补充 → 更新 `modules/<module>.md`
- 如果是一个"架构洞察" → 更新 `architecture.md`
- 如果是一个"坏味道发现" → 追加到 `refactor.md`

然后在 `log.json` 加一条 `## [YYYY-MM-DD] query | <问题摘要>` 的日志。

**口诀**：每次查询都应该让 wiki 比之前更厚一点。

### 什么时候**不**回填

- 问题非常琐碎（"这个变量在哪一行定义的"）
- 答案只对当前对话有用（"我现在跑这段代码的命令是什么"）
- 用户明确说"不用记"

### 答案格式

根据问题性质选择合适的输出形式：

- **解释类问题** → 直接文字回答 + wiki/源码引用
- **对比类问题**（"A 和 B 的区别？"）→ 表格
- **流程类问题**（"请求是怎么处理的？"）→ mermaid 时序图或编号步骤
- **"改这个要动哪些地方"** → 清单 + 影响面分析，强烈建议直接写成一个新的 concepts 页（"影响面分析：<修改点>"）
- **"有几个地方做了 X"** → 列表 + 每个地方的文件/行号

## Lint：wiki 健康检查

扫描到一定规模（例如扫完 50+ 文件）之后，或者用户主动要求，做一次健康检查。目标是发现 wiki 自身的质量问题。

### 检查清单

逐项过，每项的结果写进一个**临时报告**（不直接写进 wiki），然后和用户一起决定哪些要修。

#### 1. 孤儿页（没有入链的页面）

```bash
# 找 files/ 下的所有页面，看每个是不是被别的页面引用
for f in wiki/files/*.md; do
  name=$(basename "$f" .md)
  count=$(grep -rc "$name" wiki/ --include="*.md" | grep -v ":0$" | wc -l)
  if [ "$count" -le 1 ]; then
    echo "ORPHAN: $f (引用数 $count)"
  fi
done
```

孤儿的 files 页**通常是 OK 的**（不是每个文件都会被别的 wiki 页面直接引用），但孤儿的 concepts 或 modules 页是异常信号——说明创建时没建立关联。

#### 2. 悬挂链接（指向不存在的页面）

```bash
# 找所有 markdown 相对链接，检查目标文件是否存在
rg -o '\[.*?\]\(\./[^)]+\)' wiki/ --no-filename | \
  sed 's/.*(\(.*\))/\1/' | sort -u | \
  while read link; do
    [ -f "wiki/${link#./}" ] || echo "BROKEN: $link"
  done
```

#### 3. 矛盾的描述

这项只能靠读。挑选 3-5 个可能出问题的组合：
- 同一个类在不同页面里的描述是否一致？
- `architecture.md` 里的模块职责和对应 `modules/xxx.md` 的"一句话"是否一致？
- `refactor.md` 里的建议是否已经被后续扫描的文件隐含否定了？

对每个发现的矛盾，问自己："是哪一边过时了？"通常较早的页面过时，以较新的为准更新较早的。

#### 4. 过期内容

```bash
# 看哪些页面的 last_updated 太旧（比如超过两周）
rg "^last_updated:" wiki/ --no-heading | sort
```

如果源码对应文件最近改过（`scan.py rescan` 会把它们标回 pending），但对应的 wiki 页面没更新，就是过期。

#### 5. 应该但没建的 concepts 页

扫描 modules 和 files 页的正文，找出**反复出现但没有自己页面**的概念。例如你发现有 5 个 files 页都提到"权限规则引擎"，但 `concepts/` 下没有这一页，就是一个建议新建的信号。

可以用简单的统计：

```bash
# 列出 concepts 页的标题
for f in wiki/concepts/*.md; do
  head -1 "$f" | sed 's/# //'
done > /tmp/existing_concepts.txt

# 人工或 LLM 检查：哪些概念在 modules/files 页里反复出现但不在这份清单里？
```

#### 6. refactor.md 的分布

看 refactor.md 里的条目分布：
- 是不是集中在某一两个文件？那些文件可能需要优先重写
- 有没有"严重"条目积累了很久？应该建议用户处理
- 有没有条目因为新的扫描发现已经过时？

#### 7. architecture.md 的覆盖度

对比 `scan.py status` 的进度和 architecture.md 的成熟度声明（页面顶部的 `coverage` 字段）：
- 如果扫描进度 > 70% 但 architecture 还写着"初步猜测"，说明你忘了更新它
- 如果扫描进度还很低但 architecture 已经写得很满，说明你可能**过度推断**了，要回头审视

### lint 报告模板

把发现整理成报告，交给用户：

```markdown
# Wiki 健康检查报告 | 2026-04-10

## 摘要
- 孤儿 concepts/modules 页：2
- 悬挂链接：1
- 发现的矛盾：3
- 过期页面：5
- 建议新建的 concepts 页：4
- refactor.md 新观察：2

## 孤儿页
1. `concepts/插件注册.md` —— 无入链。原因：在 modules/core.md 里被提到但没加链接。建议：更新 modules/core.md。
2. ...

## 悬挂链接
1. `architecture.md` 引用了 `modules/auth.md`，但该文件不存在。可能是拼写错误或后来改名。

## 矛盾
1. `files/src__core__scheduler.md` 说 `_tick` 是 100ms 周期，但 `algorithm/任务调度.md` 说 50ms。源码核对：确认是 100ms，`algorithm/任务调度.md` 过时，需要更新。
2. ...

## 过期页面（>14 天未更新但源码有变动）
- `files/src__api__handlers.md` —— 源码 2026-04-08 改过
- ...

## 建议新建的 concepts 页
1. "权限规则引擎" —— 在 5 个文件中出现
2. ...

## refactor.md 新观察
- "严重"条目 2 条已存在 > 30 天，建议和用户确认处理计划
- ...
```

把这份报告交给用户，问："要我把哪些问题修掉？"然后按他的指示做。

### lint 之后

每次 lint 结束，在 log.json 追加一条：

```markdown
## [2026-04-10] lint | round-2
- 检查了 7 项，发现 17 个问题
- 已修复：孤儿页 2，悬挂链接 1，矛盾 3，过期页面 5
- 留待后续：建议新建 concepts 页 4（用户要先看更多代码再决定）
- 报告见本次对话
```

## Query 和 Lint 的频率

没有硬性规定，但一般节奏：

- **每扫 10-15 个文件**：小迷你汇报（不算完整 lint），只报告本批次触及的页面和新增的 refactor 条目
- **每扫 50 个文件**：跑一次完整 lint
- **扫描完毕时**：跑一次完整 lint + 和用户一起读一遍 architecture.md
- **用户问了一个跨越多文件的大问题后**：lint 的"矛盾"检查（因为你可能刚刚更新了多页，要确保它们一致）
