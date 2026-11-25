import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ImportBuiltinModal } from "./ImportBuiltinModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@agentscope-ai/design", async () => {
  const { Button, Modal, Tooltip } = await import("antd");
  return { Button, Modal, Tooltip };
});

describe("ImportBuiltinModal removed language", () => {
  it.each(["en", "zh"] as const)(
    "imports the remaining %s package when the installed language was removed",
    async (availableLanguage) => {
      const user = userEvent.setup();
      const removedLanguage = availableLanguage === "en" ? "zh" : "en";
      const onConfirm = vi.fn().mockResolvedValue(undefined);

      render(
        <ImportBuiltinModal
          open
          loading={false}
          sources={[
            {
              name: "alpha",
              current_language: removedLanguage,
              current_version_text: "1.0",
              available_languages: [availableLanguage],
              languages: {
                [availableLanguage]: {
                  language: availableLanguage,
                  version_text: "2.0",
                  status: "removed",
                },
              },
              status: "removed",
            },
          ]}
          notice={null}
          defaultLanguage={removedLanguage}
          onCancel={vi.fn()}
          onConfirm={onConfirm}
        />,
      );

      expect(screen.getByText("skillPool.statusRemoved")).toBeInTheDocument();
      await user.click(screen.getByText("alpha"));
      await user.click(screen.getByRole("button", { name: "OK" }));

      expect(onConfirm).toHaveBeenCalledExactlyOnceWith([
        { skill_name: "alpha", language: availableLanguage },
      ]);
    },
  );
});
