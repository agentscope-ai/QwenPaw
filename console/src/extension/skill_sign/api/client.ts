import { getApiUrl } from "@/api/config";
import { buildAuthHeaders } from "@/api/authHeaders";

export interface SkillSecureImportResult {
  imported: string[];
  count: number;
  verification?: {
    valid: boolean;
    signer?: string | null;
    package_sha256?: string;
    error?: string;
  };
  conflicts?: Array<{
    reason: string;
    skill_name: string;
    suggested_name: string;
  }>;
}

export async function uploadSkillPoolSecureImport(
  file: File,
  signatureFile: File,
  options?: {
    target_name?: string;
    rename_map?: Record<string, string>;
  },
): Promise<SkillSecureImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("signature", signatureFile);

  const params = new URLSearchParams();
  if (options?.target_name) {
    params.set("target_name", options.target_name);
  }
  if (options?.rename_map && Object.keys(options.rename_map).length) {
    params.set("rename_map", JSON.stringify(options.rename_map));
  }
  const qs = params.toString();
  const url = getApiUrl(`/skills/pool/secure-import${qs ? `?${qs}` : ""}`);
  const headers = buildAuthHeaders();

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!response.ok) {
    const text = await response.text();
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      throw new Error(`${response.status} ${response.statusText} - ${text}`);
    }
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return (await response.json()) as SkillSecureImportResult;
}
