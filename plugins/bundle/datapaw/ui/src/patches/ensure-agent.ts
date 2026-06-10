import {
  DATAPAW_AGENT_ID,
  FIRST_INSTALL_KEY,
  STORAGE_KEY,
} from "../lib/constants";

const LAST_USED_KEY = "qwenpaw-last-used-agent";

export function ensureDefaultAgent(): void {
  if (localStorage.getItem(FIRST_INSTALL_KEY)) return;

  localStorage.setItem(FIRST_INSTALL_KEY, "true");

  function writeAgentToStorage(): void {
    localStorage.setItem(LAST_USED_KEY, DATAPAW_AGENT_ID);
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        parsed.state = parsed.state || {};
        parsed.state.selectedAgent = DATAPAW_AGENT_ID;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
      } else {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: DATAPAW_AGENT_ID,
              agents: [],
              lastChatIdByAgent: {},
            },
          }),
        );
      }
    } catch {
      /* ignore */
    }
    try {
      const sessionRaw = sessionStorage.getItem(STORAGE_KEY);
      if (sessionRaw) {
        const parsed = JSON.parse(sessionRaw);
        parsed.state = parsed.state || {};
        parsed.state.selectedAgent = DATAPAW_AGENT_ID;
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
      }
    } catch {
      /* ignore */
    }
  }

  writeAgentToStorage();
  window.addEventListener("beforeunload", writeAgentToStorage, { once: true });

  console.info(
    `[datapaw] Set default agent to ${DATAPAW_AGENT_ID} for first-time user`,
  );
}
