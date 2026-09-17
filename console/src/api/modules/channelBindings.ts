import { request } from "../request";

export interface UserChannelBinding {
  id: string;
  channel_type: string;
  display_name: string;
  enabled: boolean;
  config: Record<string, unknown>;
  configured_secret_fields: string[];
}

export interface UserChannelBindingInput {
  display_name: string;
  enabled: boolean;
  config: Record<string, unknown>;
}

const bindingPath = (agentId: string): string =>
  `/agents/${encodeURIComponent(agentId)}/channel-bindings`;

export const channelBindingsApi = {
  listUserChannelBindings: (agentId: string) =>
    request<UserChannelBinding[]>(bindingPath(agentId)),

  updateUserChannelBinding: (
    agentId: string,
    channelType: string,
    body: UserChannelBindingInput,
  ) =>
    request<UserChannelBinding>(
      `${bindingPath(agentId)}/${encodeURIComponent(channelType)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  deleteUserChannelBinding: (agentId: string, channelType: string) =>
    request<{ success: true }>(
      `${bindingPath(agentId)}/${encodeURIComponent(channelType)}`,
      { method: "DELETE" },
    ),

  checkUserChannelBindingConflict: (
    agentId: string,
    channelType: string,
    config: Record<string, unknown>,
  ) =>
    request<{ conflict: boolean }>(
      `${bindingPath(agentId)}/${encodeURIComponent(
        channelType,
      )}/conflict-check`,
      {
        method: "POST",
        body: JSON.stringify({ config }),
      },
    ),
};
