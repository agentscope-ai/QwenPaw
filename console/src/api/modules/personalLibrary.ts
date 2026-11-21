import { request } from "../request";
import {
  withAgentRequestContext,
  type AgentRequestContext,
} from "./agentRequestContext";

export interface PersonalLibraryDocument {
  id: string;
  relative_path: string;
  name: string;
  media_type: string;
  size: number;
  sha256: string;
  created_at: string;
  updated_at: string;
}

export interface PersonalLibraryDocumentContent
  extends PersonalLibraryDocument {
  content: string;
  offset: number;
  next_offset: number | null;
  truncated: boolean;
}

export interface PersonalLibraryIndexStatus {
  document_id: string;
  status:
    | "pending"
    | "ready"
    | "partial"
    | "empty"
    | "unsupported"
    | "too_large"
    | "failed"
    | "missing"
    | "unavailable";
  indexed_characters: number;
  updated_at: string | null;
}

export const personalLibraryApi = {
  indexStatus: (context: AgentRequestContext) =>
    request<PersonalLibraryIndexStatus[]>(
      "/console/personal-library/index",
      withAgentRequestContext(undefined, context),
    ),
  rebuildIndex: (
    documentIds: string[],
    context: AgentRequestContext,
    signal?: AbortSignal,
  ) =>
    request<PersonalLibraryIndexStatus[]>(
      "/console/personal-library/index/rebuild",
      {
        ...withAgentRequestContext(undefined, context),
        method: "POST",
        signal,
        timeout: 120_000,
        body: JSON.stringify({ document_ids: documentIds }),
      },
    ),
  listPage: (
    query: string,
    offset: number,
    limit: number,
    context: AgentRequestContext,
    signal?: AbortSignal,
  ) =>
    request<{ items: PersonalLibraryDocument[]; total: number }>(
      `/console/personal-library/documents/page?${new URLSearchParams({
        query,
        offset: String(offset),
        limit: String(limit),
      })}`,
      withAgentRequestContext({ signal }, context),
    ),
  move: (
    document: PersonalLibraryDocument,
    destinationPath: string,
    context: AgentRequestContext,
  ) =>
    request<PersonalLibraryDocument>(
      `/console/personal-library/documents/${encodeURIComponent(document.id)}`,
      withAgentRequestContext(
        {
          method: "PATCH",
          body: JSON.stringify({
            destination_path: destinationPath,
            expected_updated_at: document.updated_at,
          }),
        },
        context,
      ),
    ),
  remove: (document: PersonalLibraryDocument, context: AgentRequestContext) =>
    request<void>(
      `/console/personal-library/documents/${encodeURIComponent(
        document.id,
      )}?${new URLSearchParams({ expected_updated_at: document.updated_at })}`,
      withAgentRequestContext({ method: "DELETE" }, context),
    ),
  downloadUrl: (id: string) =>
    `/api/console/personal-library/documents/${encodeURIComponent(
      id,
    )}/download`,
  list: (path = "", context?: AgentRequestContext) => {
    const url = `/console/personal-library/documents?path=${encodeURIComponent(
      path,
    )}`;
    const options = withAgentRequestContext(undefined, context);
    return options
      ? request<PersonalLibraryDocument[]>(url, options)
      : request<PersonalLibraryDocument[]>(url);
  },
  upload: (file: File, context?: AgentRequestContext) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<PersonalLibraryDocument>(
      "/console/personal-library/documents/upload",
      withAgentRequestContext({ method: "POST", body: formData }, context),
    );
  },
  readText: (
    id: string,
    offset = 0,
    limit = 65_536,
    context?: AgentRequestContext,
  ) =>
    request<PersonalLibraryDocumentContent>(
      `/console/personal-library/documents/${encodeURIComponent(
        id,
      )}/text?offset=${offset}&limit=${limit}`,
      withAgentRequestContext(undefined, context),
    ),
  copyAttachment: (
    input: {
      attachmentId: string;
      destinationPath: string;
      overwrite?: boolean;
    },
    context?: AgentRequestContext,
  ) =>
    request<PersonalLibraryDocument>(
      "/console/personal-library/imports/attachment",
      {
        ...withAgentRequestContext(undefined, context),
        method: "POST",
        body: JSON.stringify({
          attachment_id: input.attachmentId,
          destination_path: input.destinationPath,
          overwrite: input.overwrite ?? false,
        }),
      },
    ),
  copyRuntimeFile: (
    input: {
      sourcePath: string;
      destinationPath: string;
      overwrite?: boolean;
    },
    context?: AgentRequestContext,
  ) =>
    request<PersonalLibraryDocument>(
      "/console/personal-library/imports/runtime-file",
      {
        ...withAgentRequestContext(undefined, context),
        method: "POST",
        body: JSON.stringify({
          source_path: input.sourcePath,
          destination_path: input.destinationPath,
          overwrite: input.overwrite ?? false,
        }),
      },
    ),
  copyArtifact: (
    input: {
      sourcePath: string;
      destinationPath: string;
      overwrite?: boolean;
    },
    context?: AgentRequestContext,
  ) =>
    request<PersonalLibraryDocument>(
      "/console/personal-library/imports/artifact",
      {
        ...withAgentRequestContext(undefined, context),
        method: "POST",
        body: JSON.stringify({
          source_path: input.sourcePath,
          destination_path: input.destinationPath,
          overwrite: input.overwrite ?? false,
        }),
      },
    ),
};
