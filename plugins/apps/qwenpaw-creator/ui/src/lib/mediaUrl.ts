import { getGeneratedMediaUrl } from "@/api/creator";

export function displayMediaUrl(url?: string | null): string {
  if (!url) return "";
  return getGeneratedMediaUrl(url);
}
