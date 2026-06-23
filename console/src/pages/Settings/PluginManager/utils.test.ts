import { describe, it, expect } from "vitest";
import { readDirEntry } from "./utils";

interface FakeEntryOptions {
  fullPath: string;
}

function makeFileEntry(opts: FakeEntryOptions, file: File): FileSystemEntry {
  const entry = {
    isFile: true,
    isDirectory: false,
    fullPath: opts.fullPath,
    file: (resolve: (f: File) => void) => resolve(file),
  };
  return entry as unknown as FileSystemEntry;
}

function makeDirEntry(
  opts: FakeEntryOptions,
  batches: FileSystemEntry[][],
): FileSystemDirectoryEntry {
  let callIndex = 0;
  const entry = {
    isFile: false,
    isDirectory: true,
    fullPath: opts.fullPath,
    createReader: () => ({
      readEntries: (resolve: (entries: FileSystemEntry[]) => void) => {
        resolve(callIndex < batches.length ? batches[callIndex++] : []);
      },
    }),
  };
  return entry as unknown as FileSystemDirectoryEntry;
}

describe("readDirEntry", () => {
  it("reads a flat directory of files and strips the leading slash from paths", async () => {
    const file1 = new File(["a"], "a.txt");
    const file2 = new File(["b"], "b.txt");
    const root = makeDirEntry({ fullPath: "/root" }, [
      [
        makeFileEntry({ fullPath: "/root/a.txt" }, file1),
        makeFileEntry({ fullPath: "/root/b.txt" }, file2),
      ],
      [],
    ]);
    const result = await readDirEntry(root);
    expect(result).toEqual([
      { path: "root/a.txt", file: file1 },
      { path: "root/b.txt", file: file2 },
    ]);
  });

  it("recursively descends into nested subdirectories and flattens the result", async () => {
    const innerFile = new File(["c"], "c.txt");
    const outerFile = new File(["d"], "d.txt");
    const sub = makeDirEntry({ fullPath: "/root/sub" }, [
      [makeFileEntry({ fullPath: "/root/sub/c.txt" }, innerFile)],
      [],
    ]);
    const root = makeDirEntry({ fullPath: "/root" }, [
      [
        makeFileEntry({ fullPath: "/root/d.txt" }, outerFile),
        sub as unknown as FileSystemEntry,
      ],
      [],
    ]);
    const result = await readDirEntry(root);
    expect(result).toEqual([
      { path: "root/d.txt", file: outerFile },
      { path: "root/sub/c.txt", file: innerFile },
    ]);
  });

  it("returns an empty array when the directory is empty", async () => {
    const root = makeDirEntry({ fullPath: "/empty" }, [[]]);
    const result = await readDirEntry(root);
    expect(result).toEqual([]);
  });
});
