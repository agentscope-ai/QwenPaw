import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (file: string) =>
  readFileSync(join(process.cwd(), "src", file), "utf8");

describe("shell interaction density", () => {
  it("uses the desktop hit token for shell icon actions", () => {
    for (const file of [
      "layouts/sidebarA.module.less",
      "layouts/dockableSidebar.module.less",
      "layouts/sidebarSessionList.module.less",
      "components/SessionItem/sessionItem.module.less",
      "components/SessionGroupHeader/SessionGroupHeader.module.less",
      "components/AgentSelector/index.module.less",
      "pages/Chat/components/ChatHeaderTitle/index.module.less",
    ]) {
      expect(read(file)).toContain("var(--app-hit-desktop)");
    }
  });

  it("provides coarse-pointer 44px hit targets across the shell", () => {
    for (const file of [
      "layouts/sidebarA.module.less",
      "layouts/dockableSidebar.module.less",
      "layouts/sidebarSessionList.module.less",
      "components/SessionItem/sessionItem.module.less",
      "components/AgentSelector/index.module.less",
      "pages/SettingsCenter/index.module.less",
      "pages/Chat/components/ChatHeaderTitle/index.module.less",
    ]) {
      const source = read(file);
      expect(source).toContain("any-pointer: coarse");
      expect(source).toContain("var(--app-hit-touch)");
    }
  });
});
