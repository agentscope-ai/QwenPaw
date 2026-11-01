import { describe, expect, it } from "vitest";
import i18next, { i18nReady } from "../../i18n";
import { resolveLocalized } from "../../plugins/registry/types";
import { BUILTIN_ROUTES } from "./builtinRoutes";

const EXPECTED_ROUTES = [
  ["core.root", "/"],
  ["core.chat", "/chat/*"],
  ["core.settings-center", "/settings/*"],
  ["core.files", "/files"],
  ["core.channels", "/channels"],
  ["core.sessions", "/sessions"],
  ["core.inbox", "/inbox"],
  ["core.cron-jobs", "/cron-jobs"],
  ["core.heartbeat", "/heartbeat"],
  ["core.skills", "/skills"],
  ["core.skill-pool", "/skill-pool"],
  ["core.tools", "/tools"],
  ["core.mcp", "/mcp"],
  ["core.acp", "/acp"],
  ["core.acp-alias", "/ACP"],
  ["core.checkpoints", "/checkpoints"],
  ["core.agents", "/agents"],
  ["core.models", "/models"],
  ["core.environments", "/environments"],
  ["core.offload-policy", "/offload-policy"],
  ["core.agent-config", "/agent-config"],
  ["core.security", "/security"],
  ["core.token-usage", "/token-usage"],
  ["core.agent-stats", "/agent-stats"],
  ["core.voice-transcription", "/voice-transcription"],
  ["core.debug", "/debug"],
  ["core.backups", "/backups"],
  ["core.marketplace", "/market"],
  ["core.import", "/imports"],
  ["core.app-center.embed", "/apps/:appId"],
] as const;

describe("BUILTIN_ROUTES", () => {
  it("keeps every existing route id and path stable", () => {
    expect(BUILTIN_ROUTES.map(({ id, path }) => [id, path])).toEqual(
      EXPECTED_ROUTES,
    );
  });

  it("declares information architecture metadata for every route", () => {
    for (const route of BUILTIN_ROUTES) {
      expect(route.meta, route.id).toMatchObject({
        domain: expect.stringMatching(
          /^(chat|tasks|workspace|extensions|settings)$/,
        ),
        title: expect.anything(),
        scope: expect.stringMatching(/^(global|agent|session|workspace)$/),
        layout: expect.stringMatching(/^(standard|workbench|immersive)$/),
        navigation: expect.stringMatching(
          /^(rail|context|settings|search-only)$/,
        ),
      });
    }
  });

  it("keeps the canonical ACP route case-sensitive", () => {
    const canonicalRoute = BUILTIN_ROUTES.find(({ id }) => id === "core.acp");

    expect(canonicalRoute?.caseSensitive).toBe(true);
  });

  it("resolves titles with the requested locale", async () => {
    await i18nReady;
    const previousLanguage = i18next.language;

    try {
      await i18next.changeLanguage("zh");
      const chatRoute = BUILTIN_ROUTES.find(({ id }) => id === "core.chat");

      expect(resolveLocalized(chatRoute?.meta?.title, "en")).toBe("Chat");
    } finally {
      await i18next.changeLanguage(previousLanguage);
    }
  });
});
