import { create } from "zustand";
import type {
  ExecutionAuthorizationApproval,
  ExecutionAuthorizationView,
} from "@/contracts/creator";
import {
  approveFileExecutionAuthorization,
  declineFileExecutionAuthorization,
  listFileExecutionAuthorizations,
  newClientId,
} from "@/api/creator";
import i18n from "@/i18n";

const actionRetryIds = new Map<string, string>();

interface ExecutionAuthorizationState {
  projectId: string | null;
  items: ExecutionAuthorizationView[];
  loading: boolean;
  /** Loaded at least once; poll refreshes never drop UI back to loading. */
  loaded: boolean;
  error: string | null;
  bindProject: (projectId: string) => void;
  load: (projectId: string) => Promise<void>;
  approve: (
    authorizationId: string,
    request: ExecutionAuthorizationApproval,
  ) => Promise<void>;
  decline: (
    authorizationId: string,
    authorizationToken: string,
  ) => Promise<void>;
  reset: () => void;
}

export const useExecutionAuthorizationStore =
  create<ExecutionAuthorizationState>((set, get) => {
    let epoch = 0;
    let requestId = 0;

    const bindProject = (projectId: string) => {
      if (get().projectId === projectId) return;
      epoch += 1;
      requestId = 0;
      set({
        projectId,
        items: [],
        loading: false,
        loaded: false,
        error: null,
      });
    };

    return {
      projectId: null,
      items: [],
      loading: false,
      loaded: false,
      error: null,
      bindProject,
      load: async (projectId) => {
        bindProject(projectId);
        const requestEpoch = epoch;
        const currentRequestId = ++requestId;
        set({ loading: true, error: null });
        try {
          const response = await listFileExecutionAuthorizations(projectId);
          if (
            requestEpoch !== epoch ||
            currentRequestId !== requestId ||
            get().projectId !== projectId
          )
            return;
          set({
            items: response.items ?? [],
            loading: false,
            loaded: true,
            error: null,
          });
        } catch (error) {
          if (
            requestEpoch === epoch &&
            currentRequestId === requestId &&
            get().projectId === projectId
          )
            set({ loading: false, error: (error as Error).message });
          throw error;
        }
      },
      approve: async (authorizationId, request) => {
        const { projectId } = get();
        if (!projectId) throw new Error(i18n.t("store.noActiveProject"));
        const signature = JSON.stringify({
          projectId,
          authorizationId,
          request,
          action: "approve",
        });
        const clientRequestId =
          actionRetryIds.get(signature) ?? newClientId("authorization-approve");
        actionRetryIds.set(signature, clientRequestId);
        const updated = await approveFileExecutionAuthorization(
          projectId,
          authorizationId,
          request,
          clientRequestId,
        );
        actionRetryIds.delete(signature);
        if (get().projectId !== projectId) return;
        requestId += 1;
        set((state) => ({
          items: state.items.map((item) =>
            item.id === authorizationId ? updated : item,
          ),
        }));
      },
      decline: async (authorizationId, authorizationToken) => {
        const { projectId } = get();
        if (!projectId) throw new Error(i18n.t("store.noActiveProject"));
        const request = { authorizationToken };
        const signature = JSON.stringify({
          projectId,
          authorizationId,
          request,
          action: "decline",
        });
        const clientRequestId =
          actionRetryIds.get(signature) ?? newClientId("authorization-decline");
        actionRetryIds.set(signature, clientRequestId);
        const updated = await declineFileExecutionAuthorization(
          projectId,
          authorizationId,
          request,
          clientRequestId,
        );
        actionRetryIds.delete(signature);
        if (get().projectId !== projectId) return;
        requestId += 1;
        set((state) => ({
          items: state.items.map((item) =>
            item.id === authorizationId ? updated : item,
          ),
        }));
      },
      reset: () => {
        epoch += 1;
        requestId = 0;
        set({
          projectId: null,
          items: [],
          loading: false,
          loaded: false,
          error: null,
        });
      },
    };
  });
