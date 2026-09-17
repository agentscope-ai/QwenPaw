import { expect, it, vi } from "vitest";
import { screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import { request } from "@/api/request";
import CheckpointsPage from "./index";

vi.mock("@/api/request", () => ({ request: vi.fn() }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en" },
  }),
}));

it("Legacy 手动快照请求保留所选会话的非空身份", async () => {
  const sent: unknown[] = [];
  vi.mocked(request).mockImplementation(async (url, options) => {
    if (url.endsWith("/status"))
      return {
        auto_enabled: true,
        has_checkpoints: false,
        scope: "legacy",
        restore_mode: "in_place",
      };
    if (url.includes("/graph?"))
      return {
        nodes: [],
        sessions: [
          {
            session_key: "legacy-key",
            session_id: "legacy-session",
            user_id: "legacy-user",
            channel: "console",
            title: "Legacy session",
            checkpoint_count: 0,
          },
        ],
        summary: { total: 0, auto: 0, snapshots: 0, safety: 0, heads: 0 },
        truncated: false,
      };
    if (url.endsWith("/snapshot")) {
      const body = JSON.parse(String(options?.body));
      sent.push(body);
      if (body.user_id !== "legacy-user")
        throw new Error("Legacy identity mismatch");
      return { ref: "refs/snap/legacy", commit: "a".repeat(40) };
    }
    throw new Error(`Unexpected URL ${url}`);
  });
  renderWithProviders(<CheckpointsPage />);
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", { name: "checkpoints.snapshot" }),
  );
  const dialog = await screen.findByRole("dialog");
  await user.click(
    within(dialog).getByRole("button", { name: "checkpoints.snapshot" }),
  );
  await waitFor(() =>
    expect(sent).toEqual([
      {
        session_id: "legacy-session",
        user_id: "legacy-user",
        channel: "console",
        name: "",
      },
    ]),
  );
});
