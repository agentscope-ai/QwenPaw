import { create } from "zustand";
import type { ModelConfigData } from "@/contracts/creator";
import { getModelConfig } from "@/api/creator";

interface ModelConfigState {
  config: ModelConfigData | null;
  refresh: () => Promise<void>;
}

// The home page reads the model config from several places at once (the
// LLM banner, the composer's required-model hint, the header badges). They
// share this single snapshot so saving the config in any one modal updates
// every indicator without a page reload; concurrent refreshes collapse into
// one request.
let inflight: Promise<void> | null = null;

export const useModelConfigStore = create<ModelConfigState>((set) => ({
  config: null,
  refresh: () => {
    if (!inflight) {
      inflight = getModelConfig()
        .then((config) => set({ config }))
        .catch(() => set({ config: null }))
        .finally(() => {
          inflight = null;
        });
    }
    return inflight;
  },
}));
