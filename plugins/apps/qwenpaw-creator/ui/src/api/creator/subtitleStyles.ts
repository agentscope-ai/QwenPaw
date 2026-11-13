import type {
  SubtitleAnimationPolicy,
  SubtitleStyle,
  UserSubtitleStyle,
  UserSubtitleStyleListResponse,
} from "@/contracts/creator";
import { creatorRequest, jsonBody } from "./client";

/** The style window's current picks, named for later reuse. */
export interface UserSubtitleStyleBundle {
  name: string;
  description?: string;
  packId?: string | null;
  style?: SubtitleStyle | null;
  animation?: SubtitleAnimationPolicy | null;
}

export function listUserSubtitleStyles(): Promise<
  UserSubtitleStyleListResponse
> {
  return creatorRequest<UserSubtitleStyleListResponse>(
    "/subtitle-packs/custom",
  );
}

export function saveUserSubtitleStyle(
  bundle: UserSubtitleStyleBundle,
): Promise<UserSubtitleStyle> {
  return creatorRequest<UserSubtitleStyle>("/subtitle-packs/custom", {
    method: "POST",
    body: jsonBody(bundle),
  });
}

export function updateUserSubtitleStyle(
  styleId: string,
  bundle: UserSubtitleStyleBundle,
): Promise<UserSubtitleStyle> {
  return creatorRequest<UserSubtitleStyle>(
    `/subtitle-packs/custom/${encodeURIComponent(styleId)}`,
    {
      method: "PUT",
      body: jsonBody(bundle),
    },
  );
}

export function deleteUserSubtitleStyle(
  styleId: string,
): Promise<{ deleted: string }> {
  return creatorRequest<{ deleted: string }>(
    `/subtitle-packs/custom/${encodeURIComponent(styleId)}`,
    { method: "DELETE" },
  );
}
