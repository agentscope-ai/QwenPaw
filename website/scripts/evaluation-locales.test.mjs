import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const load = async (lang) =>
  JSON.parse(
    await readFile(
      new URL(`../src/i18n/locales/evaluation.${lang}.json`, import.meta.url),
      "utf8",
    ),
  );
function leaves(value, prefix = "") {
  if (typeof value === "string") return [[prefix, value]];
  return Object.entries(value).flatMap(([key, child]) =>
    leaves(child, `${prefix}.${key}`),
  );
}
test("Evaluation translations have identical keys and interpolation variables", async () => {
  const en = new Map(leaves(await load("en")));
  const zh = new Map(leaves(await load("zh")));
  assert.deepEqual([...en.keys()].sort(), [...zh.keys()].sort());
  for (const [key, english] of en) {
    const chinese = zh.get(key);
    assert(english.trim() && chinese.trim(), `Empty translation: ${key}`);
    const placeholders = (text) =>
      [...text.matchAll(/{{(\w+)}}/g)].map((match) => match[1]).sort();
    assert.deepEqual(placeholders(english), placeholders(chinese), key);
    assert(
      !/\p{Script=Han}/u.test(english),
      `Chinese text in English resource: ${key}`,
    );
  }
});
