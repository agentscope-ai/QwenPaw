import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const pageStyles = readFileSync(
  join(process.cwd(), "src/pages/Settings/Models/index.module.less"),
  "utf8",
);
const poolStyles = readFileSync(
  join(
    process.cwd(),
    "src/pages/Settings/Models/components/modals/ModelPool.module.less",
  ),
  "utf8",
);
const configEditorStyles = readFileSync(
  join(
    process.cwd(),
    "src/pages/Settings/Models/components/modals/ModelConfigEditor.module.less",
  ),
  "utf8",
);
const agentDefaultsStyles = readFileSync(
  join(
    process.cwd(),
    "src/pages/Settings/Models/AgentModelDefaults.module.less",
  ),
  "utf8",
);
const selectorStyles = readFileSync(
  join(process.cwd(), "src/pages/Chat/ModelSelector/index.module.less"),
  "utf8",
);
const thinkingStyles = readFileSync(
  join(process.cwd(), "src/features/thinking/thinking.module.less"),
  "utf8",
);

describe("model settings visual language", () => {
  it("keeps provider hover feedback restrained and consistent", () => {
    expect(pageStyles).toContain("--reflection-silver: transparent;");
    expect(pageStyles).toContain("border-radius: 16px;");
    expect(pageStyles).toContain(
      "background: color-mix(in srgb, var(--app-accent) 2%, var(--app-surface));",
    );
    expect(pageStyles).toContain("transform: none;");
  });

  it("uses one polished shell across model dialogs", () => {
    expect(pageStyles).toContain(".modelManageModal,");
    expect(pageStyles).toContain(".modelConfirmModal");
    expect(pageStyles).toContain("border-radius: 20px;");
    expect(pageStyles).toContain(
      "box-shadow: 0 22px 64px rgb(49 35 22 / 14%);",
    );
    expect(poolStyles).toContain(".subModal");
  });

  it("gives model rows the same quiet accent hover as tool cards", () => {
    expect(poolStyles).toContain("--reflection-silver: transparent;");
    expect(poolStyles).toContain(".entry:hover,");
    expect(poolStyles).toContain("border-color: var(--app-accent-border);");
    expect(poolStyles).toContain("box-shadow: 0 6px 18px rgb(49 35 22 / 5%);");
  });

  it("keeps model detail settings compact without fixed empty space", () => {
    expect(poolStyles).toContain(".detailModal");
    expect(poolStyles).toContain("height: min(520px, calc(100dvh - 160px));");
    expect(configEditorStyles).toContain("border-radius: 14px;");
    expect(configEditorStyles).toContain(".settingRow");
  });

  it("uses the quiet settings treatment for the current agent", () => {
    expect(agentDefaultsStyles).toContain("--reflection-silver: transparent;");
    expect(agentDefaultsStyles).toContain(".choice:hover,");
    expect(selectorStyles).toContain(
      '.agentModelSettings[data-surface="settings"]',
    );
    expect(thinkingStyles).toContain('.control[data-tone="quiet"]');
  });
});
