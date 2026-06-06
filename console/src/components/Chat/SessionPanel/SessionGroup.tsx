import React from "react";
import type { SessionGroup as SessionGroupType } from "../types";
import SessionItem from "./SessionItem";
import styles from "./SessionPanel.module.less";

interface SessionGroupProps {
  group: SessionGroupType;
  activeSessionId: string | null;
  editingId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onStartEdit: (id: string) => void;
  onCancelEdit: () => void;
}

const SessionGroup: React.FC<SessionGroupProps> = ({
  group,
  activeSessionId,
  editingId,
  onSelect,
  onDelete,
  onRename,
  onPin,
  onStartEdit,
  onCancelEdit,
}) => {
  if (group.sessions.length === 0) return null;

  return (
    <div className={styles.sessionGroup}>
      <div className={styles.groupLabel}>{group.label}</div>
      {group.sessions.map((session) => (
        <SessionItem
          key={session.id}
          session={session}
          isActive={session.id === activeSessionId}
          isEditing={session.id === editingId}
          onClick={() => onSelect(session.id)}
          onDelete={() => onDelete(session.id)}
          onRename={(name) => onRename(session.id, name)}
          onPin={() => onPin(session.id, !session.pinned)}
          onStartEdit={() => onStartEdit(session.id)}
          onCancelEdit={onCancelEdit}
        />
      ))}
    </div>
  );
};

export default SessionGroup;
