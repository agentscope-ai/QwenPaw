import { request } from "./request";
import {
  getAccessSessionGeneration,
  subscribeAccessSessionGeneration,
} from "./authSession";
import { buildAuthHeaders } from "./authHeaders";
import { getApiUrl } from "./config";
import { useAuthStore } from "../stores/authStore";

interface Entry {
  promise: Promise<unknown>;
  expires: number;
}
const reads = new Map<string, Entry>();
let revision = 0;

export function invalidateModelReads() {
  revision += 1;
  reads.clear();
}
subscribeAccessSessionGeneration(invalidateModelReads);

/** Coalesce metadata reads only; model authorization is still checked on send. */
export function readModelMetadata<T>(
  path: string,
  agentId?: string,
): Promise<T> {
  const generation = getAccessSessionGeneration();
  const capturedRevision = revision;
  const userId = useAuthStore.getState().user?.id;
  const agent = agentId ?? buildAuthHeaders()["X-Agent-Id"];
  const key = JSON.stringify([getApiUrl(path), generation, userId, agent]);
  const existing = reads.get(key);
  if (existing && existing.expires > Date.now())
    return existing.promise as Promise<T>;
  for (const [key, entry] of reads)
    if (entry.expires <= Date.now()) reads.delete(key);
  if (reads.size >= 64) reads.delete(reads.keys().next().value!);
  const entry: Entry = { promise: Promise.resolve(), expires: Infinity };
  entry.promise = request<T>(
    path,
    agent ? { headers: { "X-Agent-Id": agent } } : undefined,
  )
    .then((value) => {
      if (
        generation !== getAccessSessionGeneration() ||
        capturedRevision !== revision ||
        userId !== useAuthStore.getState().user?.id
      )
        throw new DOMException("Model context changed", "AbortError");
      entry.expires = Date.now() + 1000;
      return value;
    })
    .catch((error) => {
      if (reads.get(key) === entry) reads.delete(key);
      throw error;
    });
  reads.set(key, entry);
  return entry.promise as Promise<T>;
}
