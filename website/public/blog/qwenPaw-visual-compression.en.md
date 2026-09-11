---
title: "QwenPaw Visual Compression: Rendering Long Context as Images"
date: 2026-08-04
author: QwenPaw Team
tags: [Visual Compression, Context Management, Multimodal, QwenPaw 2.0.1]
cover: https://img.alicdn.com/imgextra/i2/O1CN01yY4c4j29VUb5FtFhp_!!6000000008073-2-tps-1561-858.png
excerpt: "In QwenPaw 2.0.1, Visual Compression renders long, stable history, tool descriptions, and large results into high-density images so multimodal models read the same information with fewer tokens—while a truth table and recovery tool preserve verbatim access to the source."
---

# QwenPaw Visual Compression: Rendering Long Context as Images

## What Is Visual Compression?

Context cost in Agent scenarios usually does not come from a long user question. It comes from the fact that the same batch of system prompts, tool descriptions, file contents, and history messages is fed back into the model on every “model → tool → model” loop. As rounds accumulate, the truly new information may be small, but the model still has to re-read a large body of existing context each round. As a result, a seemingly simple task can end up consuming tens or even hundreds of thousands of tokens.

A common mitigation is text summarization, such as `/compact`: rewriting a long history into a shorter passage. It is good at preserving topics and main conclusions, but the cost is a complete rewrite of the original history. Once a summary omits or misstates a detail, the model usually has no evidence to tell where the error happened. Frequent summarization can also break cache hits; and for inherently repetitive content like ultra-long system prompts or large sets of tool definitions, text summarization hardly solves the problem at its root.

An interesting optimization direction is to render part of the text context into images and let a multimodal model read them. Text input token cost usually grows roughly linearly with character count, while image input cost depends more on image resolution, the number of visual patches, and the model's specific visual encoding scheme—not strictly on how many characters the image contains. This opens up a potential compression space: the same batch of history messages, tool descriptions, or file contents may cost a hundred thousand tokens as direct text input, but after compact typesetting and rendering into a few high-density images, the resulting visual token cost can be much lower. In other words, visual context is not just “letting the model look at screenshots”—it is using two-dimensional pixel space to re-encode text that could previously only be laid out linearly. For Agents that call tools frequently and run for many rounds, this can become a new form of context compression.

![image](https://img.alicdn.com/imgextra/i2/O1CN01yY4c4j29VUb5FtFhp_!!6000000008073-2-tps-1561-858.png)

Of course, “**the original text is in the pixels**” does not equal “**the model can read the original text back verbatim**.” Images eventually become visual blocks; when the font size, resolution, or attention is insufficient, the model may misread. Therefore, images and summaries can be seen as two different lossy approaches:

- Summaries actively rewrite semantics;

- Images preserve layout but shift the recognition burden to the visual model.

## How QwenPaw Performs Visual Compression

In QwenPaw 2.0.1, a **Visual Compression** feature was introduced, referencing the implementation of [pxpipe](https://github.com/teamchong/pxpipe). In QwenPaw's implementation, when Visual Compression is enabled, QwenPaw copies the current round's messages and tool definitions before the model request goes out, and only rewrites that temporary request. The full original text is still preserved in the session. When the next round starts, the system re-evaluates from the original messages which content is worth compressing.

What it does can be summarized as: **keep recent and current work, fold stable older content, and preserve recovery paths.**

- **Keep recent and current work.** The current user request, the most recent rounds of messages, unfinished tool calls, and core tool protocols all stay in the text channel. QwenPaw only conservatively migrates longer, more stable background descriptions.

- **Fold stable older content.** Earlier conversations, long background, and large successful tool results can be chunked and rendered into images. History messages are re-chunked only when they cross a new boundary, avoiding re-rendering everything every round and keeping the cache more stable.

- **Preserve recovery paths.** When content is too short, there are too many images, the layout is incomplete, or the visual cost is not clearly lower than the original text, it stays as text without visual rendering. Different parts are tried and abandoned independently. If an anomaly occurs—such as missing media or an out-of-control image budget—the whole request rolls back to the native original.

![image](https://img.alicdn.com/imgextra/i1/O1CN018fyB8CrJq2H3bJe1_!!6000000002179-2-tps-1774-887.png)

When actually generating images, QwenPaw does not summarize or rewrite the original text. It only tidies excess whitespace, preserves line breaks, indentation, role labels, and tool-call structure, and selects different text densities based on `low`, `medium`, or `high`. The system completes pagination and cost estimation first, and only generates images after confirming the conversion is worthwhile. Under the same content and configuration, the local rendering result can also be reused.

But **images are not suitable for preserving every exact value.** Paths, version numbers, URLs, numbers, and random IDs—misreading a single character can lead to a completely different result. Visual Compact therefore adds two layers of protection:

- The **truth table** extracts a set of high-risk strings from the original text and places them as native text next to the image, so the model can read them directly.

- The **recovery tool** lets the model go back to the real source text. Each content block replaced by an image gets an ID; the model can use the **recovery tool** `recover_visual_context` to preview the original text, search keywords, read specific lines, or page through by character position.

For example, after a model understands a long validation report from a visual page and needs to confirm a final state, it can directly use the corresponding Recovery ID to search for `final_status`. The result comes from the pre-conversion original text, not from re-OCR'ing the image.

In summary, QwenPaw splits the context of a single request across three channels:

- Text carries the current task, important rules, tool protocols, and high-risk fields;

- Images carry long, stable background, old history, and large results;

- The recovery tool returns source text when precise confirmation is needed.

## Using Visual Compression in QwenPaw

Enable Visual Compression in **Run Configuration** - **Context Management**, and select a model with **multimodal capability** as the conversation model to start using it ([related docs](https://qwenpaw.agentscope.io/docs/context)).

- Whether a model has multimodal capability can be checked on the **Models** page.

- Low / Medium / High correspond to compression strength. Low is the recommended default—the compression strength is usually already sufficient.

### ![image](https://img.alicdn.com/imgextra/i3/O1CN018oQOki9AAeK5o1aM_!!6000000003470-2-tps-2860-1318.png)

## Observing Visual Compression Results

To test the effect, I designed a fictional e-commerce service incident investigation scenario locally. The working directory contained order CSV, service logs, meeting notes, emails, product specs, JavaScript source, and test files. The Agent had to complete nine tasks in sequence: counting data, analyzing logs, locating problems across files, extracting action items from meeting notes, modifying code and running tests, and recalling a precise ID it had seen earlier without re-reading the file. The nine tasks ran in the same session. The later the task, the longer the history—closer to the context accumulation problem a real Agent faces.

The experiment compared four modes:

- **Text only**: Visual Compression off, all history kept as text;

- **Low**: Only compress obviously large content;

- **Medium**: Start compressing earlier, with denser image layout;

- **High**: Widest compression range, densest layout.

Each mode was run independently three times—12 sessions and 108 tasks in total—using the Qwen3.7-Plus model.

### Results

| Mode      | Tasks passed | Input       | Uncached   | Cached      | Output    | Calls  | Images  | Compressed chars |
| --------- | ------------ | ----------- | ---------- | ----------- | --------- | ------ | ------- | ---------------- |
| Text only | **27/27**    | 3,185,875   | 283,934    | 2,873,088   | 12,594    | 42     | —       | —                |
| Low       | 25/27        | 563,740     | 123,164    | 440,576     | 10,952    | 40     | 243     | 5,490,583        |
| Medium    | 26/27        | **389,183** | **93,398** | **306,816** | **8,815** | **35** | **165** | **4,228,839**    |
| High      | 25/27        | 419,363     | 97,000     | 331,008     | 9,987     | 38     | 208     | 5,439,353        |

- **Visual Compression drastically reduced input.** Low, Medium, and High reduced Input by **82.3%**, **87.8%**, and **86.8%** respectively. Even excluding cache reads, Uncached input still dropped by **56.6%**, **67.1%**, and **65.8%**. This shows that Visual Compression significantly cuts token cost in long-context, multi-round scenarios.

- **Medium had the best overall result.** Its Input, Uncached input, and model call count were all the lowest among the three visual modes, completing 26 of 27 tasks.

  - On the first run, the Agent repeatedly rewrote a script after mis-parsing a CSV column, pushing a single run's Input to 720,376; the latter two runs were only 389,183 and 350,166.

  - Low failed once by skipping the recovery call and simply stating it could not find the answer; another run produced the correct result file but the final reply leaked content from the previous task. Medium's only failure was missing one of three code files to update—closer to an ordinary execution omission.

  - High failed the same precise-recall task two rounds in a row: the model knew the recovery tool existed but never actually called it. The first round succeeded but needed three recovery calls to find the answer. **More recovery and model calls can offset the tokens saved, and taking the wrong path can even directly cause task failure.**

**Takeaway**: In this experiment, Medium had the best overall result. But a default config needs to face more unknown tasks, so the more conservative **Low** is still recommended—it preserves more native text and recent history while already achieving about an 82% Input reduction. For validated long-log and long-tool-result scenarios, **Medium** can be used; **High** should be used with caution for now.

## Conclusion

This article introduced how to use and experience “**Visual Compression**” in the new QwenPaw release. As native multimodal capabilities grow stronger, designs for visual-assisted context and memory will likely become more common.

### Content Best Suited for Visual Compression

- **Long, old semantic background.** Historical logs, old tool results, spec background, and meeting notes usually require understanding themes and relationships rather than transcribing every character verbatim.

- **Cache not yet warm, or text approaching the window budget.** At that point, reducing input is more likely to produce real value.

- **Content that can be traced back to source.** When the original text is still locatable via a Recovery ID, the image only needs to handle “understand first,” not “permanently lossless storage.”

### Risks of Visual Compression

- **Per-character exact values.** Short hex, SHA, UUID, amounts, version numbers, paths, table cells, and code snippets—misreading one character can lead to a completely wrong result.

- **Safety rules and current instructions.** Instructions inside an image may be less salient than native system/user text; you cannot assume that switching a role or modality preserves the exact same compliance strength.

- **Irrecoverable external state.** Current inventory, order status, and workspace file contents should be re-queried from the real source, not treated as a fact database built from old visual pages.

### Treat the Gains Cautiously

Note that the original text may already be hitting a cheap cache. Converting it to an image changes the prefix, and the first conversion or boundary advance can rebuild the cache. Meanwhile, visual prefill, local rendering, and model behavior divergence also affect latency. If an image makes the model check one more time or call one more tool, the extra round of reasoning carries the full context again—enough to wipe out the local input savings.

Therefore, in practice, enable Visual Compression conservatively; do not decide usage based solely on token savings.

- The cache-read probability of the original text and the stability of the image prefix;

- The model's multimodal capability, whether multiple recoveries are needed to finish a task, and whether extra rounds of tool-call cost are introduced;

- The actual model pricing—whether image tokens and text tokens are billed equally.

### The Future of Visual Compression

Although pricing considerations are more complex, the context-space savings give long-horizon tasks more room. At the same time, the current QwenPaw implementation still has room for improvement, such as:

- Improving the recall capability of the Recovery tool;

- Tuning rendering parameters;

- The context layout after visual compression.

With further optimization of the above, the feature will become more stable and usable.

## Further Reading

- [QwenPaw Context Management documentation](https://qwenpaw.agentscope.io/docs/context)
- [QwenPaw v2.0.1 release notes](https://qwenpaw.agentscope.io/release-notes#v2.0.1)
- [pxpipe implementation reference](https://github.com/teamchong/pxpipe)
- [QwenPaw GitHub repository](https://github.com/agentscope-ai/QwenPaw)
