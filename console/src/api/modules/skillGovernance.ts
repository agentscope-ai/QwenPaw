import { scopedSkillRequest, type SkillScope } from "../skillScope";
import type {
  GovernedSkill,
  SkillCatalogItem,
  SkillGrant,
  SkillPreview,
  SkillPublicationRequest,
  SkillRequestDetail,
  SkillSourceState,
  SkillTargetResult,
  SkillBroadcastConfirmation,
} from "../types/skillGovernance";

export function createSkillGovernanceApi(scope: SkillScope) {
  const call = <T>(path: string, method?: string, body?: unknown) =>
    scopedSkillRequest<T>(scope, path, {
      ...(method ? { method } : {}),
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  const governance = "/skill-governance";
  const item = (id: string) => `${governance}/items/${encodeURIComponent(id)}`;
  const publication = (id: string) =>
    `${governance}/requests/${encodeURIComponent(id)}`;
  return {
    catalog: () =>
      call<{ items: SkillCatalogItem[] }>(
        `/skill-catalog?agent_id=${encodeURIComponent(scope.agentId)}`,
      ),
    installed: () =>
      call<{ items: SkillSourceState[] }>(
        `/agent-skills?agent_id=${encodeURIComponent(scope.agentId)}`,
      ),
    load: (skillId: string, expectedHash?: string) =>
      call<SkillSourceState>("/agent-skills/load", "POST", {
        agent_id: scope.agentId,
        skill_id: skillId,
        ...(expectedHash
          ? { overwrite: true, expected_content_hash: expectedHash }
          : {}),
      }),
    update: (name: string, hash: string) =>
      call<SkillSourceState>(
        `/agent-skills/${encodeURIComponent(name)}/update`,
        "POST",
        { agent_id: scope.agentId, expected_content_hash: hash },
      ),
    restore: (name: string, hash: string) =>
      call<SkillSourceState>(
        `/agent-skills/${encodeURIComponent(name)}/restore`,
        "POST",
        { agent_id: scope.agentId, expected_content_hash: hash },
      ),
    submit: (name: string) =>
      call<{
        id: string;
        status: "pending";
        review_version: number;
        content_hash: string;
      }>(`${governance}/requests`, "POST", {
        agent_id: scope.agentId,
        skill_name: name,
      }),
    preview: () =>
      call<{ items: SkillPreview[] }>(
        `${governance}/initialization/preview`,
        "POST",
      ),
    register: (items: SkillPreview[]) =>
      call<{ imported: number }>(
        `${governance}/initialization/import`,
        "POST",
        { items },
      ),
    items: () => call<{ items: GovernedSkill[] }>(`${governance}/items`),
    setStatus: (id: string, enabled: boolean) =>
      call<{ id: string; status: string }>(`${item(id)}/status`, "PATCH", {
        enabled,
      }),
    grants: (id: string) =>
      call<{ grants: SkillGrant[] }>(`${item(id)}/agent-grants`),
    grant: (id: string, agentId: string, enabled: boolean) =>
      call(`${item(id)}/agent-grants/${encodeURIComponent(agentId)}`, "PUT", {
        enabled,
      }),
    requests: () =>
      call<{ requests: SkillPublicationRequest[] }>(`${governance}/requests`),
    detail: (id: string) => call<SkillRequestDetail>(publication(id)),
    file: (id: string, path: string) =>
      call<{ content: string }>(
        `${publication(id)}/files/${path
          .split("/")
          .map(encodeURIComponent)
          .join("/")}`,
      ),
    review: (
      id: string,
      decision: "approve" | "reject",
      expectedVersion: number,
      note: string,
    ) =>
      call(`${publication(id)}/review`, "POST", {
        decision,
        expected_version: expectedVersion,
        note,
      }),
    broadcast: (
      id: string,
      agentIds: string[],
      previewOnly: boolean,
      overwrite = false,
      confirmations?: Record<string, SkillBroadcastConfirmation>,
    ) =>
      call<{ results: SkillTargetResult[] }>(`${item(id)}/broadcast`, "POST", {
        agent_ids: agentIds,
        preview_only: previewOnly,
        overwrite,
        ...(confirmations ? { confirmations } : {}),
      }),
  };
}
