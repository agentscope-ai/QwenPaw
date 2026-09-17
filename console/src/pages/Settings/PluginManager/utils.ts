/** Recursively read a directory entry into flat {path, file} pairs. */
export async function readDirEntry(
  entry: FileSystemDirectoryEntry,
): Promise<Array<{ path: string; file: File }>> {
  const result: Array<{ path: string; file: File }> = [];
  const reader = entry.createReader();

  const readBatch = (): Promise<FileSystemEntry[]> =>
    new Promise((resolve, reject) => reader.readEntries(resolve, reject));

  let batch: FileSystemEntry[];
  do {
    batch = await readBatch();
    for (const element of batch) {
      if (element.isFile) {
        const file = await new Promise<File>((resolve, reject) =>
          (element as FileSystemFileEntry).file(resolve, reject),
        );
        result.push({ path: element.fullPath.replace(/^\//, ""), file });
      } else if (element.isDirectory) {
        const sub = await readDirEntry(element as FileSystemDirectoryEntry);
        result.push(...sub);
      }
    }
  } while (batch.length > 0);

  return result;
}

export type LocalSelection =
  | { kind: "zip"; name: string; file: File }
  | {
      kind: "folder";
      name: string;
      entries: Array<{ path: string; file: File }>;
    };
