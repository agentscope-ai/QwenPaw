import { expect, it } from "vitest";
import { encodeFileMention, rewriteFileMentions } from "./fileMentions";
import { splitFileReferences } from "./fileReferenceFormatting";

it("renders a stable four-source token as a readable atomic file chip", () => {
  const parts = splitFileReferences(encodeFileMention({source:"artifact", id:"id-1", name:"需求.md"}));
  expect(parts[0].reference).toMatchObject({kind:"chat-file", path:"需求.md", documentId:"id-1", source:"artifact"});
});

it("binds same-name documents to distinct source ids and only references the last user turn", () => {
  const first = encodeFileMention({source:"personal_library", id:"doc-1", name:"需求.md"});
  const second = encodeFileMention({source:"artifact", id:"artifact-2", name:"需求.md"});
  const result = rewriteFileMentions([
    {role:"user", content:first},
    {role:"assistant", content:"ok"},
    {role:"user", content:`分析 ${second}`},
  ]);
  expect(result.references).toEqual([{source:"artifact",id:"artifact-2"}]);
  expect(result.input[2].content).toBe("分析 @需求.md");
  expect(result.input[2].metadata).toMatchObject({qwenpaw_display_text: `分析 ${second}`});
});

it("preserves escaped labels and all four sources", () => {
  const input = ["temporary", "personal_library", "agent_profile", "artifact"].map(source =>
    encodeFileMention({source: source as "temporary", id:"a", name:"a]b.md"})).join(" ");
  const result = rewriteFileMentions([{role:"user",content:input}]);
  expect(result.references).toHaveLength(4);
  expect(result.input[0].content).toBe("@a]b.md @a]b.md @a]b.md @a]b.md");
});
