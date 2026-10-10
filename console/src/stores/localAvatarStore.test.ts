import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_AVATAR, useLocalAvatar } from "./localAvatarStore";
import { avatarApi, type AvatarProfile } from "../api/modules/avatars";
vi.mock("../api/modules/avatars", () => ({
  avatarApi: {
    get: vi.fn(),
    select: vi.fn(),
    upload: vi.fn(),
    image: vi.fn(),
  },
}));
const profile: AvatarProfile = {
  selected: "gif",
  history: [
    { id: "gif", mime: "image/gif", created_at: "2026-09-22T00:00:00Z" },
  ],
};
beforeEach(() => {
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:avatar"),
      revokeObjectURL: vi.fn(),
    }),
  );
  useLocalAvatar.getState().reset();
  vi.clearAllMocks();
  vi.mocked(avatarApi.image).mockResolvedValue(
    new Blob(["GIF89a"], { type: "image/gif" }),
  );
});
describe("server-owned avatars", () => {
  it("loads server selection and restores default without deleting history", async () => {
    expect(DEFAULT_AVATAR).toBe("/qwenpaw-avatar.gif");
    vi.mocked(avatarApi.get).mockResolvedValue(profile);
    await useLocalAvatar.getState().load();
    expect(useLocalAvatar.getState().images.gif).toBe("blob:avatar");
    vi.mocked(avatarApi.select).mockResolvedValue({
      ...profile,
      selected: null,
    });
    await useLocalAvatar.getState().select(null);
    expect(avatarApi.select).toHaveBeenCalledWith(null);
    expect(useLocalAvatar.getState().selected).toBeNull();
    expect(useLocalAvatar.getState().history).toEqual(profile.history);
  });
  it("ignores an old account response after authentication changes", async () => {
    let resolve!: (value: AvatarProfile) => void;
    vi.mocked(avatarApi.get).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const pending = useLocalAvatar.getState().load();
    useLocalAvatar.getState().reset();
    resolve(profile);
    await pending;
    expect(useLocalAvatar.getState().selected).toBeNull();
    expect(avatarApi.image).not.toHaveBeenCalled();
  });
  it("does not let a late initial load undo a selection", async () => {
    let resolve!: (value: AvatarProfile) => void;
    vi.mocked(avatarApi.get).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const pending = useLocalAvatar.getState().load();
    vi.mocked(avatarApi.select).mockResolvedValue(profile);
    await useLocalAvatar.getState().select("gif");
    resolve({ selected: null, history: [] });
    await pending;
    expect(useLocalAvatar.getState().selected).toBe("gif");
  });
  it("revokes account image URLs on reset", async () => {
    vi.mocked(avatarApi.get).mockResolvedValue(profile);
    await useLocalAvatar.getState().load();
    useLocalAvatar.getState().reset();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:avatar");
    expect(useLocalAvatar.getState().images).toEqual({});
  });
});
