# -*- coding: utf-8 -*-
"""Domain prompts for knowledge dream extraction."""

from __future__ import annotations

BUSINESS_EXTRACT_PROMPT_ZH = """\
你是业务知识提炼助手。从以下每日记忆笔记中提取可复用的业务知识单元。

要求：
1. 只提取稳定、可复用的业务口径、流程、实体定义、决策与约束。
2. 忽略闲聊、临时任务状态、敏感隐私。
3. 覆盖笔记中出现的全部稳定可复用口径，不要只抽最显眼的几条；同一实体只输出一个单元。
4. 每个单元给出：name（短标题）、bucket（business/wiki | business/procedure | business/personal）、
   summary（1-3句，笔记里出现的定义、边界、例外、约束尽量写进摘要）、confidence（0-1）、signals（依据片段摘要列表，尽量用笔记原句）、
   action_hint（可选：CREATE / CORROBORATE / REFINE / CORRECT；MERGE 视为 REFINE 别名）、
   merge_target（可选：当 action_hint 为 CORROBORATE/REFINE/CORRECT 时，给出要并入/修正的已有 KB 节点标题）、
   links（可选：关联的已有 KB 节点标题列表，用于追溯）。
5. 动作语义：
   - CREATE：全新抽象，库中尚无相同实体。
   - CORROBORATE：同一抽象再次出现，只需追加来源/强化置信，不必改正文口径。
   - REFINE：同一抽象有新边界、步骤、前提或细节需要并入正文。
   - CORRECT：新材料修正旧口径中的错误或冲突。
6. 最多返回 {max_units} 个单元；达到上限时优先更稳定、被多处提及的。
7. 填写 merge_target 时必须使用下列已有节点的标题；同一实体不要另起「X-补充」之类新名去 CREATE。
8. 严格输出 JSON 数组，不要 markdown 围栏。

已有知识库节点（name / bucket / description）：
{existing_nodes}

每日笔记：
{daily_corpus}
"""

BUSINESS_EXTRACT_PROMPT_EN = """\
You extract reusable business knowledge units from daily memory notes.

Rules:
1. Keep durable business definitions, procedures, entity facts, decisions,
   and constraints.
2. Skip chit-chat, transient task status, and sensitive private data.
3. Cover every durable reusable claim in the notes; one unit per entity.
4. For each unit provide: name, bucket (business/wiki | business/procedure | business/personal),
   summary (1-3 sentences; include definitions, boundaries, exceptions,
   and constraints when the notes have them), confidence (0-1),
   signals (short evidence snippets, prefer verbatim phrases from the notes),
   action_hint (optional: CREATE / CORROBORATE / REFINE / CORRECT;
   MERGE is accepted as an alias of REFINE),
   merge_target (optional: when action_hint is CORROBORATE/REFINE/CORRECT, the title of
   the existing KB node to merge into / correct),
   links (optional: titles of related KB nodes for traceability).
5. Action semantics:
   - CREATE: new abstraction; no same entity in the KB yet.
   - CORROBORATE: same abstraction reappears; append provenance / boost
     confidence without rewriting the body.
   - REFINE: same abstraction gains new boundaries, steps, preconditions,
     or details that should be woven into the body.
   - CORRECT: new material fixes an error or conflict in the old body.
6. Return at most {max_units} units; if you hit the cap, keep the most
   durable, repeatedly attested claims.
7. When filling merge_target, use a title from the existing-node list below;
   do not CREATE a sibling named like "X-supplement" for the same entity.
8. Output a JSON array only — no markdown fences.

Existing KB nodes (name / bucket / description):
{existing_nodes}

Daily notes:
{daily_corpus}
"""

TESTCASE_EXTRACT_PROMPT_ZH = """\
你是测试知识提炼助手。从以下每日记忆笔记中提取可复用的测试知识单元——
包括测试场景、测试用例、测试数据、缺陷模式、测试策略。

要求：
1. 只提取可复用的测试设计/用例/数据/缺陷模式；忽略一次性执行结果、临时调试日志、敏感数据。
2. 测试用例必须可执行：明确前置条件、步骤、预期结果。模糊的"测试了一下"不要抽。
3. 覆盖笔记中出现的全部可复用测试知识；同一用例/场景只输出一个单元。
4. 每个单元给出：
   - name（短标题，如「支付-余额不足应拒绝」）
   - bucket（test/test_design | test/test_cases | test/test_data | test/defects）
   - summary（1-3句概述，覆盖可复用要点：场景边界、关键步骤/预期或缺陷模式）
   - confidence（0-1）
   - signals（依据片段摘要列表，尽量用笔记原句）
   - action_hint（可选：CREATE / CORROBORATE / REFINE / CORRECT；MERGE 视为 REFINE 别名）
   - merge_target（可选：当 action_hint 为 CORROBORATE/REFINE/CORRECT 时，给出要并入/修正的已有 KB 节点标题；不确定可空）
   - preconditions（用例前置条件；非用例类可空）
   - steps（有序测试步骤列表；非用例类可空）
   - expected（预期结果；非用例类可空）
   - priority（P0|P1|P2|P3，可空）
   - requirement_id（关联需求编号，如 REQ-123；可空）
   - links（关联的已有 KB 节点标题列表，如对应业务规则节点名，用于追溯）
5. 动作语义：
   - CREATE：全新用例/场景/缺陷模式。
   - CORROBORATE：同一用例再次被确认，追加来源即可。
   - REFINE：补步骤、前置、边界或预期。
   - CORRECT：修正错误步骤/预期。
6. test/test_design 放测试场景/等价类划分/边界设计；test/test_cases 放具体用例；
   test/test_data 放可复用测试数据集；test/defects 放沉淀的缺陷模式（不是一次性 bug）。
7. 最多返回 {max_units} 个单元；达到上限时优先更稳定、可执行的用例。
8. 填写 merge_target 时必须使用下列已有节点的标题；同一用例不要另起「X-补充」之类新名去 CREATE。
9. 严格输出 JSON 数组，不要 markdown 围栏。

已有知识库节点（name / bucket / description）：
{existing_nodes}

每日笔记：
{daily_corpus}
"""

TESTCASE_EXTRACT_PROMPT_EN = """\
You extract reusable test knowledge units from daily memory notes —
test scenarios, test cases, test data, defect patterns, test strategy.

Rules:
1. Keep only reusable test design/cases/data/defect patterns; skip one-off
   run results, transient debug logs, and sensitive data.
2. Test cases must be executable: explicit preconditions, steps, expected
   results. Vague "tested it a bit" is not a case.
3. Cover every reusable test claim in the notes; one unit per case/scenario.
4. For each unit provide:
   - name (short title, e.g. "Payment - insufficient balance should reject")
   - bucket (test/test_design | test/test_cases | test/test_data | test/defects)
   - summary (1-3 sentences covering the durable claim: scenario
     boundaries, key steps/expected, or defect pattern)
   - confidence (0-1)
   - signals (short evidence snippets; prefer verbatim phrases from the notes)
   - action_hint (optional: CREATE / CORROBORATE / REFINE / CORRECT;
     MERGE is accepted as an alias of REFINE)
   - merge_target (optional: when action_hint is CORROBORATE/REFINE/CORRECT, the title of
     the existing KB node to merge into / correct; leave empty if unsure)
   - preconditions (case preconditions; empty for non-case buckets)
   - steps (ordered test steps; empty for non-case buckets)
   - expected (expected result; empty for non-case buckets)
   - priority (P0|P1|P2|P3, may be empty)
   - requirement_id (linked requirement id, e.g. REQ-123; may be empty)
   - links (titles of related KB nodes, e.g. the business rule node, for traceability)
5. Action semantics:
   - CREATE: brand-new case / scenario / defect pattern.
   - CORROBORATE: same case reaffirmed; append provenance only.
   - REFINE: add steps, preconditions, boundaries, or expected results.
   - CORRECT: fix wrong steps / expected results.
6. test/test_design holds scenarios/equivalence-class/boundary designs;
   test/test_cases holds concrete cases; test/test_data holds reusable data
   sets; test/defects holds distilled defect patterns (not one-off bugs).
7. Return at most {max_units} units; if you hit the cap, keep the most
   durable, executable cases.
8. When filling merge_target, use a title from the existing-node list below;
   do not CREATE a sibling named like "X-supplement" for the same case.
9. Output a JSON array only — no markdown fences.

Existing KB nodes (name / bucket / description):
{existing_nodes}

Daily notes:
{daily_corpus}
"""

KB_MEMORY_GUIDANCE_ZH_EXTRA = """\
- **知识库**（`{knowledge_dir}/`）— 可跨智能体共享的正式知识（published），按域分桶：
  - `business/`：业务知识（产品/研发/测试共同维护）—— `wiki` / `procedure` / `personal`
  - `test/`：测试制品（QA 维护）—— `test_design`（场景/等价类/边界设计）、
    `test_cases`（用例本体）、`test_data`（可复用数据集）、`defects`（缺陷模式）
  - `_inbox` 为待审内容，默认不召回。

### 🔗 追溯
节点之间通过 `[[wikilink]]` 关联（如用例 → 业务规则）。链接写成工作区
相对路径（`[[knowledge/business/wiki/gmv口径.md|GMV口径]]`）。
测试域 chunk 召回会展开少量关联邻居，形成需求↔用例↔缺陷的追溯图；
业务域默认不展开邻居正文，避免弱关联当成命中。`_inbox` / `_audit` 不进入检索索引。

### 🔍 检索 scope
`memory_search(query, scope=...)`：
- `knowledge`（默认）：仅共享知识库，结果带 `[knowledge]`
- `all`：私有 digest/daily + 共享知识库，结果带 `[digest]` / `[knowledge]`
- `agent`：仅本智能体私有记忆

### 📦 分桶 bucket
`memory_search(query, bucket=...)` 只约束知识库一侧（`scope=agent` 时忽略）：
- 业务智能体默认 `business`（不含测试制品）；测试智能体默认全部 published
- `all`：全部 published 知识
- `business` / `test`：按域
- `business/wiki`、`test/test_cases` 等：按桶（含旧版扁平 `wiki` / `procedure` / `personal`）

### 🎯 召回粒度 recall
`memory_search(query, recall=...)`：
- `chunk`（默认）：返回段落级片段（含路径/行号），用于**回答具体内容**——
  「记忆里怎么说的」「引用这段」。
- `node`：返回实体级清单（每个知识单元：name + 一句话描述 + 路径 + 分桶/
  优先级等结构化字段 + 分数），用于**先盘点有哪些知识实体**——
  「围绕退款我们沉淀了哪些用例」「有哪些业务实体」。
  它不返回正文；定位到关键路径后用 `read_file` 打开该文件读全文
  （比再跑一遍 `recall="chunk"` 更准）。

经验：要「引用内容」用 `chunk`；要「盘点有什么」用 `node` 再 `read_file`；
不确定时先用 `chunk`。查正式口径时保持默认 `scope=knowledge`，不要随手改成 `all`。

用 `save_to_knowledge` 显式写入共享知识库。测试用例可传 `preconditions` / `steps` /
`expected` / `priority` / `requirement_id` / `links`，写入后即带结构化字段与追溯链接。
"""

KB_MEMORY_GUIDANCE_EN_EXTRA = """\
- **Knowledge base** (`{knowledge_dir}/`) — shared published knowledge
  across agents, namespaced by domain:
  - `business/`: business knowledge (product/dev/qa jointly maintained) —
    `wiki` / `procedure` / `personal`
  - `test/`: test artifacts (QA-owned) — `test_design` (scenarios /
    equivalence classes / boundary designs), `test_cases` (concrete
    cases), `test_data` (reusable data sets), `defects` (defect patterns)
  - `_inbox` is review-only and not recalled by default.

### 🔗 Traceability
Nodes reference each other via workspace-relative `[[wikilink]]` paths
(e.g. `[[knowledge/business/wiki/gmv.md|GMV]]`). Test-domain chunk recall
expands a few linked neighbors (requirement↔case↔defect). Business-domain
recall does not expand neighbor bodies, so weak associations are not
treated as hits. `_inbox` / `_audit` are not indexed for search.

### 🔍 Search scope
`memory_search(query, scope=...)`:
- `knowledge` (default): shared knowledge only; results tagged `[knowledge]`
- `all`: private digest/daily + shared knowledge; tagged `[digest]` /
  `[knowledge]`
- `agent`: this agent's private memory only

### 📦 Bucket
`memory_search(query, bucket=...)` narrows the knowledge side only
(`scope=agent` ignores it):
- business agents default to `business` (no test artifacts); test agents
  default to all published knowledge
- `all`: every published domain
- `business` / `test`: by domain
- `business/wiki`, `test/test_cases`, …: by bucket (legacy flat
  `wiki` / `procedure` / `personal` are accepted)

### 🎯 Recall granularity
`memory_search(query, recall=...)`:
- `chunk` (default): passage-level snippets (with path/line numbers), for
  **grounding an answer** in actual text — "what does the memory say",
  "quote this passage".
- `node`: entity-level list (name + one-line description + path + bucket /
  priority fields + score), for **surveying what knowledge entities exist**
  first — "what test cases have we captured around refund", "which
  business entities". It returns no body; once you know which path
  matters, open it with `read_file` (more precise than a second
  `recall="chunk"` search).

Rule of thumb: "here is what it says" → `chunk`; "here is what we have" →
`node` then `read_file`; when unsure, start with `chunk`. For published
definitions keep the default `scope=knowledge`; do not switch to `all`
unless you also need private notes.

Use `save_to_knowledge` to explicitly write into the shared knowledge base.
Test cases accept `preconditions` / `steps` / `expected` / `priority` /
`requirement_id` / `links`; the node is stored with structured fields and
traceability links.
"""


MERGE_PROMPT_ZH = """\
你是知识库合并助手。把一份新的知识更新并入一个已有 KB 节点的正文，输出**一份干净、无冗余**的合并后正文。

模式：{mode}
- REFINE（含历史别名 MERGE）：整合新信息（边界、步骤、前提、细节），保留所有仍有效的内容，去掉重复表述，正文只保留一份口径。
- CORRECT：新内容是对旧内容的修正；用新口径替换被修正的陈述，保留仍然成立的部分。

已有节点正文：
```
{old_body}
```

本次更新内容：
{update_block}

要求：
1. 输出**完整的合并后正文**（markdown），不要 frontmatter，不要代码围栏。
2. 保留原有正文已有的章节结构与表述风格；把"本次更新内容"整合进对应章节，去掉与已有内容重复的表述；原文没有对应章节时按更新内容自然组织。
3. 若更新含有序步骤，并入已有步骤时连续编号（如原 1-3，新增从 4 开始），不要出现两段重复的步骤列表。
4. 若更新含关联（`[[wikilink]]`），与已有关联取并集、去重，放在末尾关联段；不要删除原文已有的关联。
5. 不要新增 `## 更新` / `## 修正` 这类历史段；正文只表达当前最终口径。
6. 不要丢失原有信息（REFINE 模式），不要引入与本次更新无关的内容。
"""

MERGE_PROMPT_EN = """\
You are a knowledge-base merge assistant. Integrate a new knowledge update into an existing KB node's body and output **one clean, redundancy-free** merged body.

Mode: {mode}
- REFINE (including legacy alias MERGE): integrate new info (boundaries,
  steps, preconditions, details), keep all still-valid content, drop
  duplicate phrasing; the body holds a single statement of truth.
- CORRECT: the new content corrects the old; replace superseded statements,
  keep still-valid parts.

Existing node body:
```
{old_body}
```

This update:
{update_block}

Rules:
1. Output the **full merged body** (markdown), no frontmatter, no code fences.
2. Preserve the existing body's section structure and tone; weave "This update" into the matching sections and drop phrasing that duplicates existing content; where the original has no matching section, organize the update naturally.
3. If the update contains ordered steps, continue the existing numbering when merging (e.g. original 1-3, new starts at 4); never produce two duplicate step lists.
4. If the update contains links (`[[wikilink]]`), union them with existing links (deduped) in the links section at the end; never drop existing links.
5. Do not add `## Update` / `## Correction` history sections; the body states only the final current truth.
6. Do not drop existing info (REFINE mode); do not introduce content unrelated to this update.
"""


def build_merge_prompt(
    *,
    language: str,
    mode: str,
    old_body: str,
    unit: "KnowledgeUnit",
    formatted_links: list[str] | None = None,
    extra_units: list["KnowledgeUnit"] | None = None,
) -> str:
    """Build the LLM body-merge prompt for a unit into an existing node.

    Domain- and type-agnostic: the merge rule is "original body + update
    fields → one clean merged body". Only the unit's non-empty fields are
    rendered into the update block, so the same prompt serves business
    prose nodes (summary/links) and structured test nodes (preconditions/
    steps/expected/links). The model preserves whatever section structure
    the original body already has, continues ordered step numbering, and
    unions `[[wikilink]]` associations — no `## 更新` history sections.

    ``extra_units`` (same-batch updates targeting the same node) are
    rendered as additional update blocks so one LLM call absorbs them.

    ``CORROBORATE`` is intentionally not handled here: it is a frontmatter-
    only update that does not rewrite the body.
    """
    normalized = (mode or "REFINE").strip().upper()
    if normalized == "MERGE":
        normalized = "REFINE"
    template = MERGE_PROMPT_ZH if language.lower().startswith("zh") else MERGE_PROMPT_EN
    blocks = [
        _render_update_block(
            unit, language, formatted_links=formatted_links,
        ),
    ]
    for extra in extra_units or []:
        blocks.append(_render_update_block(extra, language))
    return template.format(
        mode=normalized,
        old_body=old_body.strip() or "(empty)",
        update_block="\n\n".join(blocks),
    )


def _render_update_block(
    unit: "KnowledgeUnit",
    language: str,
    *,
    formatted_links: list[str] | None = None,
) -> str:
    """Render the unit's non-empty fields as the "this update" block."""
    zh = language.lower().startswith("zh")
    labels = {
        "summary": "摘要" if zh else "Summary",
        "preconditions": "前置条件" if zh else "Preconditions",
        "steps": "测试步骤" if zh else "Steps",
        "expected": "预期结果" if zh else "Expected",
        "links": "关联" if zh else "Links",
    }
    lines: list[str] = []
    if unit.summary:
        lines.append(f"- {labels['summary']}: {unit.summary}")
    if unit.preconditions:
        lines.append(f"- {labels['preconditions']}: {unit.preconditions}")
    if unit.steps:
        steps = "\n".join(
            f"  {i}. {s}" for i, s in enumerate(unit.steps, start=1)
        )
        lines.append(f"- {labels['steps']}:\n{steps}")
    if unit.expected:
        lines.append(f"- {labels['expected']}: {unit.expected}")
    link_items = formatted_links if formatted_links is not None else [
        f"[[{l}]]" for l in unit.links
    ]
    if link_items:
        rendered = "\n".join(f"  - {item}" for item in link_items)
        lines.append(f"- {labels['links']}:\n{rendered}")
    return "\n".join(lines) if lines else "- （无）" if zh else "- (none)"


def build_extract_prompt(
    *,
    language: str,
    domain: str,
    daily_corpus: str,
    max_units: int,
    existing_nodes: str = "",
) -> str:
    """Build the knowledge-dream extract prompt for a domain.

    Supported domains:
    - ``business`` (default): reusable business definitions/procedures/
      entity facts/decisions/constraints.
    - ``testcase`` / ``test``: test scenarios/cases/data/defect patterns,
      with structured preconditions/steps/expected fields and traceability
      links to business nodes.

    ``existing_nodes`` is a compact catalog of published titles related
    to the daily notes (recalled / title-overlap ranked) so the model
    can fill ``merge_target`` instead of inventing sibling names.
    """
    is_test = domain.lower().startswith("test")
    zh = language.lower().startswith("zh")
    if zh:
        template = TESTCASE_EXTRACT_PROMPT_ZH if is_test else BUSINESS_EXTRACT_PROMPT_ZH
        catalog = (existing_nodes or "").strip() or "（无）"
    else:
        template = TESTCASE_EXTRACT_PROMPT_EN if is_test else BUSINESS_EXTRACT_PROMPT_EN
        catalog = (existing_nodes or "").strip() or "(none)"
    return template.format(
        max_units=max_units,
        daily_corpus=daily_corpus,
        existing_nodes=catalog,
    )


COVERAGE_EXTRACT_PROMPT_ZH = """\
你是知识补漏审查员。对照每日笔记，检查下列已抽出单元是否漏掉了仍应沉淀的稳定知识。

只补漏，不要重复已抽出的同一实体（含「X-补充」这类别名）。忽略闲聊、临时任务、敏感隐私。
最多再返回 {max_units} 个单元；没有漏项则返回空数组 []。
字段与动作语义与首次抽取相同（name / bucket / summary / confidence / signals /
action_hint / merge_target / links；测试域另含 preconditions / steps / expected /
priority / requirement_id）。
填写 merge_target 时必须使用下列已有节点的标题。
严格输出 JSON 数组，不要 markdown 围栏。

已抽出单元：
{already_extracted}

已有知识库节点（name / bucket / description）：
{existing_nodes}

每日笔记：
{daily_corpus}
"""

COVERAGE_EXTRACT_PROMPT_EN = """\
You are a knowledge-coverage reviewer. Compare the daily notes with the
units already extracted and add any durable reusable claims that were missed.

Do not repeat an entity that is already extracted (including alias titles
like "X-supplement"). Skip chit-chat, transient tasks, and private data.
Return at most {max_units} additional units; return [] if nothing was missed.
Use the same fields and action semantics as the first extract pass
(name / bucket / summary / confidence / signals / action_hint / merge_target /
links; test domain also has preconditions / steps / expected / priority /
requirement_id).
When filling merge_target, use a title from the existing-node list.
Output a JSON array only — no markdown fences.

Already extracted:
{already_extracted}

Existing KB nodes (name / bucket / description):
{existing_nodes}

Daily notes:
{daily_corpus}
"""


def build_coverage_extract_prompt(
    *,
    language: str,
    daily_corpus: str,
    max_units: int,
    already_extracted: str,
    existing_nodes: str = "",
) -> str:
    """Second-pass extract prompt: find durable claims the first pass missed."""
    zh = language.lower().startswith("zh")
    template = COVERAGE_EXTRACT_PROMPT_ZH if zh else COVERAGE_EXTRACT_PROMPT_EN
    if zh:
        catalog = (existing_nodes or "").strip() or "（无）"
        extracted = (already_extracted or "").strip() or "（无）"
    else:
        catalog = (existing_nodes or "").strip() or "(none)"
        extracted = (already_extracted or "").strip() or "(none)"
    return template.format(
        max_units=max_units,
        daily_corpus=daily_corpus,
        already_extracted=extracted,
        existing_nodes=catalog,
    )


MERGE_INTEGRITY_PROMPT_ZH = """\
你是知识库正文完整性审查员。比较合并前正文与合并后正文，判断这次重写是否丢失了不该丢失的信息，或塞进了与本次更新无关的内容。

模式：{mode}
- REFINE：合并后必须仍覆盖原文中仍然有效的口径、步骤、约束、例外与关联；允许改写措辞、去重、把新细节织入对应章节。
- CORRECT：允许用新口径替换被本次更新明确修正的旧陈述；仍须保留未被修正、仍然成立的部分。

合并前正文：
```
{old_body}
```

本次更新内容：
{update_block}

合并后正文：
```
{new_body}
```

只输出一个 JSON 对象，不要 markdown 围栏，字段：
- ok（boolean）：没有不该丢失的信息、也没有无关注入时为 true
- lost_claims（string 数组）：合并后缺失、且按当前模式不该丢的原口径（无则 []）
- injected_unrelated（string 数组）：合并后出现、但原文与本次更新都未支持的内容（无则 []）
"""

MERGE_INTEGRITY_PROMPT_EN = """\
You review a knowledge-base body rewrite for information loss and unrelated
injection.

Mode: {mode}
- REFINE: the new body must still cover every still-valid claim, step,
  constraint, exception, and link from the original; rephrasing, deduping,
  and weaving in the update are allowed.
- CORRECT: the update may replace statements it explicitly corrects; keep
  every still-valid part that the update did not supersede.

Original body:
```
{old_body}
```

This update:
{update_block}

Rewritten body:
```
{new_body}
```

Output one JSON object only — no markdown fences — with:
- ok (boolean): true when nothing that should have been kept was lost and
  nothing unrelated was injected
- lost_claims (string array): original claims missing from the rewrite that
  the current mode should have kept ([] if none)
- injected_unrelated (string array): content in the rewrite supported by
  neither the original nor this update ([] if none)
"""


def build_merge_integrity_prompt(
    *,
    language: str,
    mode: str,
    old_body: str,
    new_body: str,
    unit: "KnowledgeUnit",
    formatted_links: list[str] | None = None,
    extra_units: list["KnowledgeUnit"] | None = None,
) -> str:
    """Build the post-merge LLM prompt that checks for dropped / injected claims."""
    normalized = (mode or "REFINE").strip().upper()
    if normalized == "MERGE":
        normalized = "REFINE"
    zh = language.lower().startswith("zh")
    template = MERGE_INTEGRITY_PROMPT_ZH if zh else MERGE_INTEGRITY_PROMPT_EN
    blocks = [
        _render_update_block(
            unit, language, formatted_links=formatted_links,
        ),
    ]
    for extra in extra_units or []:
        blocks.append(_render_update_block(extra, language))
    return template.format(
        mode=normalized,
        old_body=old_body.strip() or ("（空）" if zh else "(empty)"),
        update_block="\n\n".join(blocks),
        new_body=new_body.strip() or ("（空）" if zh else "(empty)"),
    )
