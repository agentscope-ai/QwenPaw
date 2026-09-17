/**
 * SpacesPanel.tsx — Top-edge Spaces (agent) switcher.
 *
 * Revealed when the pointer hits the top edge. Each chip is an agent-space;
 * clicking one switches the whole desktop to that Space (setSelectedAgent +
 * switchSpace). Clicking the desktop background hides it (the parent drives
 * `visible` from pointer position). Complements the full Mission Control (F3).
 */
import { useMemo } from "react";
import { useAgentStore } from "../stores/agentStore";
import { useOsWindows } from "./osWindowStore";
import { buttonRoleProps } from "./a11y";
import { useOsStyles } from "./useOsStyles";
import { isAgentAvailableInChat } from "../utils/agentVisibility";

const SPACE_COLORS = [
  "#FF7F16",
  "#3b82f6",
  "#8b5cf6",
  "#10b981",
  "#ec4899",
  "#06b6d4",
  "#f59e0b",
];

function colorFor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = id.charCodeAt(i) + ((hash << 5) - hash);
  }
  return SPACE_COLORS[Math.abs(hash) % SPACE_COLORS.length];
}

export default function SpacesPanel({ visible }: { visible: boolean }) {
  const { styles, cx } = useOsStyles();
  const { agents, selectedAgent, setSelectedAgent } = useAgentStore();
  // Narrow subscription: only the space id (and the stable action).
  const spaceId = useOsWindows((s) => s.spaceId);
  const switchSpace = useOsWindows((s) => s.switchSpace);

  const spaces = useMemo(() => {
    const list = agents
      .filter(isAgentAvailableInChat)
      .map((a) => ({ id: a.id, name: a.name }));
    const selected = agents.find((agent) => agent.id === selectedAgent);
    if (
      !list.some((s) => s.id === selectedAgent) &&
      (!selected || isAgentAvailableInChat(selected))
    ) {
      list.unshift({ id: selectedAgent, name: selectedAgent });
    }
    return list;
  }, [agents, selectedAgent]);

  const selectSpace = (id: string) => {
    setSelectedAgent(id);
    switchSpace(id);
  };

  return (
    <div
      className={cx(styles.spacesPanel, !visible && styles.spacesPanelHidden)}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {spaces.map((s) => {
        const active = s.id === spaceId;
        const initial = (s.name || s.id).charAt(0).toUpperCase();
        return (
          <div
            key={s.id}
            className={cx(styles.spaceChip, active && styles.spaceChipActive)}
            onClick={() => selectSpace(s.id)}
            {...buttonRoleProps(() => selectSpace(s.id), s.name || s.id)}
          >
            <div className="avatar" style={{ background: colorFor(s.id) }}>
              {initial}
            </div>
            <div className="name">{s.name}</div>
          </div>
        );
      })}
    </div>
  );
}
