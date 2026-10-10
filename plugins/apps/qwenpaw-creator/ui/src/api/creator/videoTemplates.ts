import type {
  SaveAsTemplateRequest,
  SaveAsTemplateResponse,
  VideoTemplateListResponse,
} from "@/contracts/creator";
import { creatorRequest, jsonBody } from "./client";

export function listVideoTemplates(): Promise<VideoTemplateListResponse> {
  return creatorRequest<VideoTemplateListResponse>("/video-templates");
}

export function saveAsTemplate(
  req: SaveAsTemplateRequest,
): Promise<SaveAsTemplateResponse> {
  return creatorRequest<SaveAsTemplateResponse>("/video-templates", {
    method: "POST",
    body: jsonBody(req),
  });
}

export function deleteVideoTemplate(
  templateId: string,
): Promise<{ deleted: string }> {
  return creatorRequest<{ deleted: string }>(
    `/video-templates/${encodeURIComponent(templateId)}`,
    { method: "DELETE" },
  );
}
