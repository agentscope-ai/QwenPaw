import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export interface AvatarProfile {
  selected: string | null;
  history: { id: string; mime: string; created_at: string }[];
}
export const avatarApi = {
  get: () => request<AvatarProfile>("/profile/avatars"),
  select: (image_id: string | null) =>
    request<AvatarProfile>("/profile/avatars/selection", {
      method: "PUT",
      body: JSON.stringify({ image_id }),
    }),
  upload: (image: Blob) =>
    request<AvatarProfile>("/profile/avatars", {
      method: "POST",
      headers: { "Content-Type": image.type },
      body: image,
    }),
  image: async (id: string) => {
    const response = await fetch(
      getApiUrl(`/profile/avatars/${encodeURIComponent(id)}`),
      { headers: buildAuthHeaders() },
    );
    if (!response.ok) throw new Error("Failed to load avatar");
    return response.blob();
  },
};
