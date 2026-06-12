import { buildAuthHeaders, getApiUrl } from "./api";

export interface DataSourceRecord {
  id: string;
  type: string;
  name: string;
}

function normalizeRecord(raw: Record<string, unknown>): DataSourceRecord {
  return {
    id: String(raw.id ?? ""),
    type: String(raw.type ?? ""),
    name: String(raw.name ?? ""),
  };
}

export async function fetchDataSources(): Promise<DataSourceRecord[]> {
  const url = getApiUrl("/datapaw/data-sources");
  const res = await fetch(url, { headers: buildAuthHeaders() });
  if (!res.ok) {
    console.warn("[datapaw:data-sources] list failed", { status: res.status });
    return [];
  }

  const raw = await res.json();
  if (Array.isArray(raw)) {
    return raw.map((item) => normalizeRecord(item as Record<string, unknown>));
  }

  const body = (raw ?? {}) as Record<string, unknown>;
  const items = Array.isArray(body.items) ? body.items : [];
  return items.map((item) => normalizeRecord(item as Record<string, unknown>));
}
