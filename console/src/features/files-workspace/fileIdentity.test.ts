import { describe, expect, it } from "vitest";
import type { EditorTab } from "../../stores/codingTabsStore";
import { fileTabTarget, findOpenFileTab, workspacePath } from "./fileIdentity";

describe("legacy memory file identities", () => {
  it.each([
    {
      path: "memory::digest/note.md",
      source: "memory",
      relative: "digest/note.md",
      root: undefined,
    },
    {
      path: "workspace-root::digest/note.md",
      source: "workspace",
      relative: "digest/note.md",
      root: "workspace",
    },
    {
      path: "project:/other::digest/note.md",
      source: "workspace",
      relative: "digest/note.md",
      root: "project:/other",
    },
  ])(
    "decodes a persisted identity without optional metadata: $path",
    ({ path, source, relative, root }) => {
      expect(fileTabTarget({ path, content: "", dirty: false })).toEqual({
        source,
        path: relative,
        root,
        artifactUrl: undefined,
      });
    },
  );
  it.each([
    { daily_dir: "memory", digest_dir: "digest", prefix: "digest" },
    {
      daily_dir: "notes/daily",
      digest_dir: "notes/knowledge/",
      prefix: "knowledge",
    },
    { daily_dir: "memory", digest_dir: "memory/digest", prefix: "digest" },
  ])(
    "routes legacy digest prefixes using the configured basename: %j",
    (config) => {
      const legacy: EditorTab = {
        path: `memory::${config.prefix}/note.md`,
        content: "Unsaved digest",
        dirty: true,
      };
      const digest = `${config.digest_dir.replace(/\/$/, "")}/note.md`;
      expect(
        findOpenFileTab(
          [legacy],
          { source: "workspace", root: "workspace", path: digest },
          config,
        ),
      ).toBe(legacy);
      if (`${config.daily_dir}/${config.prefix}/note.md` !== digest) {
        expect(
          findOpenFileTab(
            [legacy],
            {
              source: "workspace",
              root: "workspace",
              path: `${config.daily_dir}/${config.prefix}/note.md`,
            },
            config,
          ),
        ).toBeUndefined();
      }
      expect(
        findOpenFileTab(
          [legacy],
          { source: "digest", path: "note.md" },
          config,
        ),
      ).toBe(legacy);
      expect(
        findOpenFileTab(
          [legacy],
          { source: "daily", path: `${config.prefix}/note.md` },
          config,
        ),
      ).toBe(
        `${config.daily_dir}/${config.prefix}/note.md` === digest
          ? legacy
          : undefined,
      );
      const workspace: EditorTab = {
        path: `workspace-root::${digest}`,
        content: "Unsaved digest",
        dirty: true,
      };
      expect(
        findOpenFileTab(
          [workspace],
          { source: "memory", path: `${config.prefix}/note.md` },
          config,
        ),
      ).toBe(workspace);
    },
  );

  it.each([
    {
      daily_dir: "notes\\daily",
      digest_dir: "notes\\knowledge",
      digestPath: "notes/knowledge/note.md",
    },
    {
      daily_dir: "notes\\daily\\",
      digest_dir: "notes\\knowledge\\",
      digestPath: "notes/knowledge/note.md",
    },
    {
      daily_dir: "notes/daily",
      digest_dir: "notes\\nested/knowledge\\",
      digestPath: "notes/nested/knowledge/note.md",
    },
  ])(
    "keeps legacy digest aliases distinct from Daily files with Windows directories: %j",
    (config) => {
      const legacy: EditorTab = {
        path: "memory::knowledge/note.md",
        content: "Unsaved digest",
        dirty: true,
      };
      expect(workspacePath(fileTabTarget(legacy), config)).toBe(
        config.digestPath,
      );
      expect(
        findOpenFileTab(
          [legacy],
          { source: "workspace", root: "workspace", path: config.digestPath },
          config,
        ),
      ).toBe(legacy);
      expect(
        findOpenFileTab(
          [legacy],
          {
            source: "workspace",
            root: "workspace",
            path: "notes/daily/knowledge/note.md",
          },
          config,
        ),
      ).toBeUndefined();
      expect(
        findOpenFileTab(
          [legacy],
          { source: "digest", path: "note.md" },
          config,
        ),
      ).toBe(legacy);
      const workspace: EditorTab = {
        path: `workspace-root::${config.digestPath}`,
        content: "Unsaved digest",
        dirty: true,
      };
      expect(
        findOpenFileTab(
          [workspace],
          { source: "memory", path: "knowledge/note.md" },
          config,
        ),
      ).toBe(workspace);
    },
  );

  it.each(["note.md", "digest.md", "digest", "digest/note"])(
    "honors daily files and the server's .md suffix for %s",
    (path) => {
      const legacy: EditorTab = {
        path: `memory::${path}`,
        content: "Unsaved",
        dirty: true,
      };
      const workspacePath = path.startsWith("digest/")
        ? "digest/note.md"
        : `memory/${path.endsWith(".md") ? path : `${path}.md`}`;
      expect(
        findOpenFileTab(
          [legacy],
          { source: "workspace", root: "workspace", path: workspacePath },
          { daily_dir: "memory", digest_dir: "digest" },
        ),
      ).toBe(legacy);
    },
  );
});
