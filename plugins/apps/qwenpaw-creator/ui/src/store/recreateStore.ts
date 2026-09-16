import { create } from "zustand";
import type { RecreateParams } from "@/api/creator";

interface RecreateState {
  params: RecreateParams | null;
  setParams: (params: RecreateParams | null) => void;
  consumeParams: () => RecreateParams | null;
}

export const useRecreateStore = create<RecreateState>((set, get) => ({
  params: null,
  setParams: (params) => set({ params }),
  consumeParams: () => {
    const { params } = get();
    set({ params: null });
    return params;
  },
}));
