import { useEffect, useMemo, useState } from "react";
import { Button, Modal } from "@agentscope-ai/design";
import { CheckOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type {
  PoolSkillSpec,
  WorkspaceSkillSummary,
} from "../../../../api/types";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import styles from "../../../Agent/Skills/index.module.less";

interface BroadcastModalProps {
  open: boolean;
  skills: PoolSkillSpec[];
  workspaces: WorkspaceSkillSummary[];
  initialSkillNames: string[];
  onCancel: () => void;
  onConfirm: (skillNames: string[], workspaceIds: string[]) => Promise<void>;
}

export function BroadcastModal({
  open,
  skills,
  workspaces,
  initialSkillNames,
  onCancel,
  onConfirm,
}: BroadcastModalProps) {
  const { t } = useTranslation();
  const [selectedSkillNames, setSelectedSkillNames] =
    useState<string[]>(initialSkillNames);
  const [selectedWorkspaceIds, setSelectedWorkspaceIds] = useState<string[]>(
    [],
  );

  const builtinSkillNames = useMemo(
    () => skills.filter((s) => s.source === "builtin").map((s) => s.name),
    [skills],
  );

  useEffect(() => {
    if (open) {
      setSelectedSkillNames(initialSkillNames);
      setSelectedWorkspaceIds([]);
    }
  }, [open, initialSkillNames]);

  const handleCancel = () => {
    setSelectedSkillNames([]);
    setSelectedWorkspaceIds([]);
    onCancel();
  };

  return (
    <Modal
      open={open}
      onCancel={handleCancel}
      onOk={() => onConfirm(selectedSkillNames, selectedWorkspaceIds)}
      okButtonProps={{
        disabled:
          selectedSkillNames.length === 0 || selectedWorkspaceIds.length === 0,
      }}
      title={t("skillPool.broadcast")}
      width={640}
    >
      <div style={{ display: "grid", gap: 12 }}>
        <div className={styles.pickerSection}>
          <div className={styles.pickerHeader}>
            <div className={styles.pickerLabel}>
              {t("skills.selectPoolItem")}
            </div>
            <div className={styles.bulkActions}>
              <Button
                size="small"
                onClick={() => setSelectedSkillNames(skills.map((s) => s.name))}
              >
                {t("agent.selectAll")}
              </Button>
              <Button
                size="small"
                onClick={() => setSelectedSkillNames(builtinSkillNames)}
              >
                {t("agent.selectBuiltin")}
              </Button>
              <Button size="small" onClick={() => setSelectedSkillNames([])}>
                {t("skills.clearSelection")}
              </Button>
            </div>
          </div>
        </div>

        <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
          {skills.map((skill) => {
            const selected = selectedSkillNames.includes(skill.name);
            return (
              <div
                key={skill.name}
                className={`${styles.pickerCard} ${styles.compactPickerCard} ${
                  selected ? styles.pickerCardSelected : ""
                }`}
                onClick={() =>
                  setSelectedSkillNames(
                    selected
                      ? selectedSkillNames.filter((n) => n !== skill.name)
                      : [...selectedSkillNames, skill.name],
                  )
                }
              >
                {selected && (
                  <span
                    className={`${styles.pickerCheck} ${styles.compactPickerCheck}`}
                  >
                    <CheckOutlined />
                  </span>
                )}
                <div
                  className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                >
                  {skill.name}
                </div>
              </div>
            );
          })}
        </div>
        <div className={styles.pickerSection}>
          <div className={styles.pickerHeader}>
            <div className={styles.pickerLabel}>
              {t("skillPool.selectWorkspaces")}
            </div>
            <div className={styles.bulkActions}>
              <Button
                size="small"
                onClick={() =>
                  setSelectedWorkspaceIds(workspaces.map((ws) => ws.agent_id))
                }
              >
                {t("skillPool.allWorkspaces")}
              </Button>
              <Button size="small" onClick={() => setSelectedWorkspaceIds([])}>
                {t("skills.clearSelection")}
              </Button>
            </div>
          </div>
        </div>

        <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
          {workspaces.map((workspace) => {
            const selected = selectedWorkspaceIds.includes(workspace.agent_id);
            return (
              <div
                key={workspace.agent_id}
                className={`${styles.pickerCard} ${styles.compactPickerCard} ${
                  selected ? styles.pickerCardSelected : ""
                }`}
                onClick={() =>
                  setSelectedWorkspaceIds(
                    selected
                      ? selectedWorkspaceIds.filter(
                          (id) => id !== workspace.agent_id,
                        )
                      : [...selectedWorkspaceIds, workspace.agent_id],
                  )
                }
              >
                {selected && (
                  <span
                    className={`${styles.pickerCheck} ${styles.compactPickerCheck}`}
                  >
                    <CheckOutlined />
                  </span>
                )}
                <div
                  className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                >
                  {getAgentDisplayName(
                    {
                      id: workspace.agent_id,
                      name: workspace.agent_name ?? "",
                    },
                    t,
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
