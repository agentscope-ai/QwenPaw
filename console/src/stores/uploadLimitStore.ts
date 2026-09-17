import { create } from "zustand";
import { settingsApi } from "../api/modules/language";

interface UploadLimitStore {
  /** Max upload size in MB, or null if unlimited */
  uploadMaxSizeMb: number | null;
  fetch: () => Promise<void>;
}

export const useUploadLimitStore = create<UploadLimitStore>((set) => ({
  uploadMaxSizeMb: null,
  fetch: async () => {
    try {
      const { upload_max_size_mb } = await settingsApi.getUploadLimit();
      set({ uploadMaxSizeMb: upload_max_size_mb });
    } catch {
      // Keep null (no limit) on failure
    }
  },
}));
