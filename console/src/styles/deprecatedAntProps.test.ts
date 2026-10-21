import { readFileSync, readdirSync } from "node:fs";
import { extname, join } from "node:path";
import { describe, expect, it } from "vitest";

const DEPRECATED_PROPS = [
  "bodyStyle=",
  "destroyOnClose",
  "overlayClassName=",
  "popupClassName=",
];

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(absolute);
    if (![".ts", ".tsx"].includes(extname(entry.name))) return [];
    if (/\.(?:test|spec)\./.test(entry.name)) return [];
    return [absolute];
  });
}

describe("Ant Design deprecation contracts", () => {
  it("does not use retired popup, card, or modal style props", () => {
    const offenders = sourceFiles(join(process.cwd(), "src")).flatMap(
      (file) => {
        const source = readFileSync(file, "utf8");
        return DEPRECATED_PROPS.filter((prop) => source.includes(prop)).map(
          (prop) => `${file}: ${prop}`,
        );
      },
    );

    expect(offenders).toEqual([]);
  });
});
