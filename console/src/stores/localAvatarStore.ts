import { create } from "zustand";
import { avatarApi, type AvatarProfile } from "../api/modules/avatars";

export const DEFAULT_AVATAR = "/qwenpaw-avatar.gif";
let generation = 0;
let revision = 0;
interface AvatarState extends AvatarProfile {
  images: Record<string, string>;
  load: () => Promise<void>;
  loadHistory: () => Promise<void>;
  select: (id: string | null) => Promise<void>;
  upload: (image: Blob) => Promise<void>;
  reset: () => void;
}

/** Server-owned identity; object URLs are an account-scoped display cache only. */
export const useLocalAvatar = create<AvatarState>((set, get) => {
  const image = async (id: string, epoch: number) => {
    if (get().images[id]) return;
    const blob = await avatarApi.image(id);
    if (epoch !== generation) return;
    const url = URL.createObjectURL(blob);
    const old = get().images[id];
    if (old) URL.revokeObjectURL(old);
    set({ images: { ...get().images, [id]: url } });
  };
  const apply = async (
    profile: AvatarProfile,
    epoch: number,
    version: number,
  ) => {
    if (epoch !== generation || version !== revision) return;
    set(profile);
    if (profile.selected) await image(profile.selected, epoch);
    if (epoch !== generation || version !== revision) return;
    const retained = new Set(profile.history.map((item) => item.id));
    const images = { ...get().images };
    for (const [id, url] of Object.entries(images)) {
      if (!retained.has(id)) {
        URL.revokeObjectURL(url);
        delete images[id];
      }
    }
    set({ images });
  };
  return {
    selected: null,
    history: [],
    images: {},
    load: async () => {
      const epoch = generation;
      const version = ++revision;
      await apply(await avatarApi.get(), epoch, version);
    },
    loadHistory: async () => {
      const epoch = generation;
      await get().load();
      if (epoch !== generation) return;
      await Promise.all(get().history.map((item) => image(item.id, epoch)));
    },
    select: async (id) => {
      const epoch = generation;
      const version = ++revision;
      await apply(await avatarApi.select(id), epoch, version);
    },
    upload: async (blob) => {
      const epoch = generation;
      const version = ++revision;
      await apply(await avatarApi.upload(blob), epoch, version);
    },
    reset: () => {
      generation++;
      Object.values(get().images).forEach((url) => URL.revokeObjectURL(url));
      set({ selected: null, history: [], images: {} });
    },
  };
});
