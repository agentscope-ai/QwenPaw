/** 锁定多用户改造前的内置页面路由与侧边栏菜单契约。 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

type BaselineManifest = {
  frontend: {
    routes: Array<{ id: string; path: string }>;
    menu: Array<{
      id: string;
      location: string;
      parentId?: string;
      route?: string;
      isGroup?: boolean;
    }>;
  };
};

const RETIRED_PRODUCT_ENTRY_IDS = new Set(["core.acp", "core.acp-alias"]);
const POST_BASELINE_ENTRY_IDS = new Set(["core.migration-preview"]);

const manifestPath = path.resolve(
  process.cwd(),
  "../tests/parity/baseline_manifest.json",
);
const routesSourcePath = path.resolve(
  process.cwd(),
  "src/layouts/registry/builtinRoutes.tsx",
);
const menuSourcePath = path.resolve(
  process.cwd(),
  "src/layouts/registry/builtinMenu.ts",
);

function loadManifest(): BaselineManifest {
  return JSON.parse(readFileSync(manifestPath, "utf-8")) as BaselineManifest;
}

function exportedArray(sourcePath: string, exportName: string): string {
  const source = readFileSync(sourcePath, "utf-8");
  const match = source.match(
    new RegExp(`export const ${exportName}:[\\s\\S]*?= \\[([\\s\\S]*?)\\n\\];`),
  );
  expect(match, `无法解析 ${exportName}`).not.toBeNull();
  return match?.[1] ?? "";
}

function stringField(objectSource: string, field: string): string | undefined {
  return objectSource.match(new RegExp(`${field}:\\s*"([^"]+)"`))?.[1];
}

function routeContracts(): Array<{ id: string; path: string }> {
  return [
    ...exportedArray(routesSourcePath, "BUILTIN_ROUTES").matchAll(
      /\{([\s\S]*?)\}/g,
    ),
  ]
    .map((match) => ({
      id: stringField(match[1], "id"),
      path: stringField(match[1], "path"),
    }))
    .filter((row): row is { id: string; path: string } =>
      Boolean(row.id && row.path),
    );
}

function menuContracts(): BaselineManifest["frontend"]["menu"] {
  return [
    ...exportedArray(menuSourcePath, "BUILTIN_MENU").matchAll(
      /\{([\s\S]*?)\}/g,
    ),
  ]
    .map((match) => {
      const source = match[1];
      const id = stringField(source, "id");
      const location = stringField(source, "location");
      if (!id || !location) return undefined;
      const parentId = stringField(source, "parentId");
      const route = stringField(source, "route");
      return {
        id,
        location,
        ...(parentId ? { parentId } : {}),
        ...(route ? { route } : {}),
        ...(source.includes("isGroup: true") ? { isGroup: true } : {}),
      };
    })
    .filter((row): row is BaselineManifest["frontend"]["menu"][number] =>
      Boolean(row),
    );
}

describe("built-in navigation baseline", () => {
  it("matches every registered built-in route", () => {
    expect(
      routeContracts().filter(
        (route) => !POST_BASELINE_ENTRY_IDS.has(route.id),
      ),
    ).toEqual(
      loadManifest().frontend.routes.filter(
        (route) => !RETIRED_PRODUCT_ENTRY_IDS.has(route.id),
      ),
    );
  });

  it("matches every registered sidebar menu item", () => {
    expect(
      menuContracts().filter((item) => !POST_BASELINE_ENTRY_IDS.has(item.id)),
    ).toEqual(
      loadManifest().frontend.menu.filter(
        (item) => !RETIRED_PRODUCT_ENTRY_IDS.has(item.id),
      ),
    );
  });

  it("does not publish the retired ACP product entry", () => {
    expect(routeContracts().some((route) => route.id.startsWith("core.acp"))).toBe(
      false,
    );
    expect(menuContracts().some((item) => item.id === "core.acp")).toBe(false);
  });
});
