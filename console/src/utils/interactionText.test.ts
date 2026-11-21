import { afterEach, expect, it } from "vitest";
import i18n from "../i18n";
import { interactionErrorText } from "./interactionText";

afterEach(() => i18n.changeLanguage("zh"));
it("shows Chinese for legacy server errors and actionable text for unknown diagnostics", async () => {
  await i18n.changeLanguage("zh");
  expect(
    interactionErrorText(
      "Account temporarily locked. Please try again later",
      423,
    ),
  ).toContain("账号暂时锁定");
  expect(
    interactionErrorText("database connection failed: password=secret", 500),
  ).toBe("服务暂时不可用，请稍后重试；如仍失败，请联系管理员");
  expect(interactionErrorText('权限不足 - {"detail":"forbidden"}', 403)).toBe(
    "权限不足",
  );
  expect(
    interactionErrorText("private_runtime_requires_owned_access", 403),
  ).toContain("自己的对话或文件中心");
});
it("honours an explicitly selected English interface", async () => {
  await i18n.changeLanguage("en");
  expect(interactionErrorText("Not authenticated", 401)).toBe(
    "Not authenticated",
  );
});
