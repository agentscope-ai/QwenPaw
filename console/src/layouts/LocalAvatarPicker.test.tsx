import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import type { ReactNode } from "react";
import LocalAvatarPicker from "./LocalAvatarPicker";
import { avatarApi } from "../api/modules/avatars";
import { useLocalAvatar } from "../stores/localAvatarStore";
vi.mock("../api/modules/avatars", () => ({
  avatarApi: {
    get: vi.fn(),
    select: vi.fn(),
    upload: vi.fn(),
    image: vi.fn(),
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../components/interaction/SharedModal", () => ({
  SharedModal: ({ open, children }: { open: boolean; children: ReactNode }) =>
    open ? <div role="dialog">{children}</div> : null,
}));
beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:gif");
  URL.revokeObjectURL = vi.fn();
  useLocalAvatar.getState().reset();
  vi.mocked(avatarApi.get).mockResolvedValue({ selected: null, history: [] });
  const history = [{ id: "gif", mime: "image/gif", created_at: "2026-09-22" }];
  vi.mocked(avatarApi.upload).mockResolvedValue({ selected: "gif", history });
  vi.mocked(avatarApi.select).mockResolvedValue({ selected: null, history });
  vi.mocked(avatarApi.image).mockResolvedValue(new Blob(["GIF89a"]));
});
it("keeps uploaded GIF bytes instead of flattening animation through canvas", async () => {
  const gif = readFileSync("public/qwenpaw-avatar.gif");
  const view = render(<LocalAvatarPicker />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "sidebar.changeAvatar" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "sidebar.uploadAvatar" }),
    ).toBeEnabled(),
  );
  const file = new File([gif], "mascot.gif", { type: "image/gif" });
  fireEvent.change(view.container.querySelector('input[type="file"]')!, {
    target: { files: [file] },
  });
  await waitFor(() => expect(useLocalAvatar.getState().selected).toBe("gif"));
  expect(avatarApi.upload).toHaveBeenCalledWith(file);
  fireEvent.click(
    screen.getByRole("button", { name: "sidebar.defaultAvatar" }),
  );
  await waitFor(() => expect(useLocalAvatar.getState().selected).toBeNull());
  expect(useLocalAvatar.getState().history).toHaveLength(1);
});
