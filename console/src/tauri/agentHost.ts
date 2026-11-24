import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { setRuntimeApiBaseUrl } from "../api/config";

export interface HostSnapshot {
  revision: number;
  generation: number;
  phase: "starting" | "ready" | "failed" | "stopping" | "stopped";
  port: number | null;
  error: string | null;
}

export const initialHostState: HostSnapshot = {
  revision: 0,
  generation: 0,
  phase: "starting",
  port: null,
  error: null,
};

/** Subscribe before reading the snapshot so attaching cannot miss a change. */
export async function connectAgentHost(
  onChange: (snapshot: HostSnapshot) => void,
): Promise<() => void> {
  let revision = -1;
  const accept = (snapshot: HostSnapshot) => {
    if (snapshot.revision <= revision) return;
    revision = snapshot.revision;
    if (snapshot.phase === "ready" && snapshot.port) {
      setRuntimeApiBaseUrl(`http://127.0.0.1:${snapshot.port}`);
    }
    onChange(snapshot);
  };
  const unlisten = await listen<HostSnapshot>(
    "qwenpaw-agent-host-state",
    (event) => accept(event.payload),
  );
  try {
    accept(await invoke<HostSnapshot>("agent_host_state"));
    return unlisten;
  } catch (error) {
    unlisten();
    throw error;
  }
}

export function restartAgentHost(): Promise<void> {
  return invoke("restart_backend");
}
