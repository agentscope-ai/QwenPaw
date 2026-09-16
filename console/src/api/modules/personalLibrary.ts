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

export const personalLibraryApi = {
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
