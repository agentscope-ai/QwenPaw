import { describe, expect, it } from "vitest";
import i18n from "../../../i18n";
import { formatGovernanceError } from "./errors";

describe("formatGovernanceError", () => {
  it("turns the last-admin conflict into a user-facing message", async () => {
    await i18n.changeLanguage("zh");

    expect(
      formatGovernanceError(
        new Error('last_active_admin - {"detail":"last_active_admin"}'),
        i18n.t,
      ),
    ).toBe("必须保留至少一个已启用的管理员");
  });
});
