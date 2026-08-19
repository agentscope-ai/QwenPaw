import { providerApi } from "../../../api/modules/provider";
import type { ActiveModelsInfo, ProviderInfo } from "../../../api/types";

export interface ModelSelectorData {
  providers: ProviderInfo[] | null;
  activeModels: ActiveModelsInfo | null;
  loadError: boolean;
}

interface ModelSelectorDataSource {
  listProviders: () => Promise<ProviderInfo[]>;
  getActiveModels: (params: {
    scope: "effective";
    agent_id: string;
  }) => Promise<ActiveModelsInfo>;
}

export async function loadModelSelectorData(
  agentId: string,
  dataSource: ModelSelectorDataSource = providerApi,
): Promise<ModelSelectorData> {
  const [providersResult, activeResult] = await Promise.allSettled([
    dataSource.listProviders(),
    dataSource.getActiveModels({
      scope: "effective",
      agent_id: agentId,
    }),
  ]);
  return {
    providers:
      providersResult.status === "fulfilled" &&
      Array.isArray(providersResult.value)
        ? providersResult.value
        : null,
    activeModels:
      activeResult.status === "fulfilled" ? activeResult.value : null,
    loadError:
      providersResult.status === "rejected" ||
      activeResult.status === "rejected",
  };
}

export async function loadActiveModels(
  agentId: string,
): Promise<ActiveModelsInfo> {
  return providerApi.getActiveModels({
    scope: "effective",
    agent_id: agentId,
  });
}

export const modelSelectorApi = {
  addModel: providerApi.addModel,
  loadActiveModels,
  loadModelSelectorData,
  setActiveLlm: providerApi.setActiveLlm,
  setModelVisibility: providerApi.setModelVisibility,
};
