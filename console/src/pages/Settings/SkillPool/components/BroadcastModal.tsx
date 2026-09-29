import { SharedModal as Modal } from "@/components/interaction/SharedModal";
import { useEffect, useMemo, useState } from "react";
import { Button, Select, Tooltip, Input } from "@agentscope-ai/design";
import NumberFlow from "@number-flow/react";
import { ArrowRight, Search, Check as CheckOutlined } from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  PoolSkillSpec,
  WorkspaceSkillSummary,
} from "../../../../api/types";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import { useSkillFilter } from "../../../Agent/Skills/useSkillFilter";
import { SkillFilterDropdown } from "../../../Agent/Skills/components/SkillFilterDropdown";
import transferStyles from "./BroadcastModal.module.less";
import styles from "../../../Agent/Skills/index.module.less";

interface BroadcastModalProps {
  open: boolean;
  surfaceId?: string;
  skills: PoolSkillSpec[];
  workspaces: WorkspaceSkillSummary[];
  initialSkillNames: string[];
  onCancel: () => void;
  onConfirm: (skillNames: string[], workspaceIds: string[]) => Promise<void>;
}

export function BroadcastModal({
  open,
  surfaceId,
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
  const [submitting, setSubmitting] = useState(false);
  const [skillQuery, setSkillQuery] = useState("");
  const [workspaceQuery, setWorkspaceQuery] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);
  const { searchTags, setSearchTags, allTags, filteredSkills } =
    useSkillFilter(skills);

  const builtinSkillNames = useMemo(
    () => skills.filter((s) => s.source === "builtin").map((s) => s.name),
    [skills],
  );

  useEffect(() => {
    if (open) {
      setSkillQuery("");
      setWorkspaceQuery("");
      setSelectedSkillNames(initialSkillNames);
      setSelectedWorkspaceIds([]);
      setSearchTags([]);
    }
  }, [open, initialSkillNames, setSearchTags]);

  const handleCancel = () => {
    setSelectedSkillNames([]);
    setSelectedWorkspaceIds([]);
    onCancel();
  };

  return (
    <Modal
      className={transferStyles.modal}
      open={open}
      surfaceId={surfaceId}
      confirmLoading={submitting}
      closable={!submitting}
      maskClosable={!submitting}
      keyboard={!submitting}
      cancelButtonProps={{ disabled: submitting }}
      onCancel={handleCancel}
      onOk={async () => {
        if (submitting) return;
        setSubmitting(true);
        try {
          await onConfirm(selectedSkillNames, selectedWorkspaceIds);
        } finally {
          setSubmitting(false);
        }
      }}
      okButtonProps={{
        disabled:
          selectedSkillNames.length === 0 || selectedWorkspaceIds.length === 0,
      }}
      title={t("skillPool.broadcast")}
      width={760}
    >
      <div className={transferStyles.summary} aria-live="polite">
        <div>
          <NumberFlow
            value={selectedSkillNames.length}
            respectMotionPreference
          />
          <span>{t("nav.skills")}</span>
        </div>
        <ArrowRight size={22} />
        <div>
          <NumberFlow
            value={selectedWorkspaceIds.length}
            respectMotionPreference
          />
          <span>{t("skillPool.selectWorkspaces")}</span>
        </div>
      </div>
      <fieldset disabled={submitting} className={transferStyles.fields}>
        <div style={{ display: "grid", gap: 12 }}>
          <div className={styles.pickerSection}>
            <div className={styles.pickerHeader}>
              <div className={styles.pickerLabel}>
                {t("skills.selectPoolItem")}
              </div>
              <div className={styles.bulkActions}>
                <Button
                  size="small"
                  type="primary"
                  onClick={() =>
                    setSelectedSkillNames(filteredSkills.map((s) => s.name))
                  }
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

          <Input
            prefix={<Search size={16} />}
            value={skillQuery}
            onChange={(event) => setSkillQuery(event.target.value)}
            placeholder={t("skills.searchPlaceholder")}
            aria-label={t("skills.searchPlaceholder")}
            allowClear
          />
          <Select
            disabled={submitting}
            mode="multiple"
            className={styles.tagSelect}
            placeholder={t("skills.filterByTag")}
            value={searchTags}
            onChange={setSearchTags}
            open={filterOpen}
            onOpenChange={setFilterOpen}
            allowClear
            maxTagCount="responsive"
            notFoundContent={<></>}
            popupRender={() =>
              allTags.length > 0 ? (
                <SkillFilterDropdown
                  allTags={allTags}
                  searchTags={searchTags}
                  setSearchTags={setSearchTags}
                  styles={styles}
                />
              ) : (
                <div className={styles.tagSelectEmpty}>
                  {t("skills.noTags")}
                </div>
              )
            }
          />

          <div
            className={`${styles.pickerGrid} ${styles.compactPickerGrid} ${transferStyles.pickerZone}`}
          >
            {filteredSkills
              .filter((skill) =>
                skill.name
                  .toLocaleLowerCase()
                  .includes(skillQuery.toLocaleLowerCase()),
              )
              .map((skill) => {
                const selected = selectedSkillNames.includes(skill.name);
                return (
                  <button
                    type="button"
                    aria-pressed={selected}
                    key={skill.name}
                    className={`${styles.pickerCard} ${
                      styles.compactPickerCard
                    } ${selected ? styles.pickerCardSelected : ""}`}
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
                        <CheckOutlined size="1em" />
                      </span>
                    )}
                    <Tooltip title={skill.name}>
                      <div
                        className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                      >
                        {skill.name}
                      </div>
                    </Tooltip>
                  </button>
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
                  type="primary"
                  onClick={() =>
                    setSelectedWorkspaceIds(workspaces.map((ws) => ws.agent_id))
                  }
                >
                  {t("skillPool.allWorkspaces")}
                </Button>
                <Button
                  size="small"
                  onClick={() => setSelectedWorkspaceIds([])}
                >
                  {t("skills.clearSelection")}
                </Button>
              </div>
            </div>
          </div>

          <Input
            prefix={<Search size={16} />}
            value={workspaceQuery}
            onChange={(event) => setWorkspaceQuery(event.target.value)}
            placeholder={t("skillPool.selectWorkspaces")}
            aria-label={t("skillPool.selectWorkspaces")}
            allowClear
          />
          <div
            className={`${styles.pickerGrid} ${styles.compactPickerGrid} ${transferStyles.pickerZone}`}
          >
            {workspaces
              .filter((workspace) =>
                `${workspace.agent_name ?? ""} ${workspace.agent_id}`
                  .toLocaleLowerCase()
                  .includes(workspaceQuery.toLocaleLowerCase()),
              )
              .map((workspace) => {
                const selected = selectedWorkspaceIds.includes(
                  workspace.agent_id,
                );
                return (
                  <button
                    type="button"
                    aria-pressed={selected}
                    key={workspace.agent_id}
                    className={`${styles.pickerCard} ${
                      styles.compactPickerCard
                    } ${selected ? styles.pickerCardSelected : ""}`}
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
                        <CheckOutlined size="1em" />
                      </span>
                    )}
                    <Tooltip title={`ID: ${workspace.agent_id}`}>
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
                    </Tooltip>
                  </button>
                );
              })}
          </div>
        </div>
      </fieldset>
    </Modal>
  );
}
