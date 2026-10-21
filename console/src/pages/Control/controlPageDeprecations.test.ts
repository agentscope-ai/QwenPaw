import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (file: string) =>
  readFileSync(join(process.cwd(), "src", file), "utf8");

describe("control page component contracts", () => {
  it("does not use deprecated Card or Popover style props", () => {
    for (const file of [
      "pages/Control/CronJobs/index.tsx",
      "pages/Control/Sessions/index.tsx",
    ]) {
      const source = read(file);
      expect(source).not.toContain("bodyStyle=");
      expect(source).not.toContain("overlayClassName=");
    }
  });

  it("keeps channel and cron mobile actions on the touch token", () => {
    for (const file of [
      "pages/Control/Channels/index.module.less",
      "pages/Control/CronJobs/index.module.less",
    ]) {
      expect(read(file)).toContain("var(--app-hit-touch)");
    }
  });
});
