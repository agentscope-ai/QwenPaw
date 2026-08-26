import {
  Button,
  Drawer,
  Form,
  Input,
  Select,
  Switch,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type {
  PoolSkillDetail,
  WorkspaceSkillSummary,
} from "../../../../api/types";
import {
  deriveInstalledFromLabel,
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  isSkillBuiltin,
} from "@/utils/skill";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import { MAX_TAGS, MAX_TAG_LENGTH } from "../../../Agent/Skills/components";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import type { PoolMode } from "../useSkillPool";
import styles from "../index.module.less";

type FormInstance = ReturnType<typeof Form.useForm>[0];

interface PoolSkillDrawerProps {
  mode: PoolMode | null;
  activeSkill: PoolSkillDetail | null;
  loading?: boolean;
  saving?: boolean;
  skillName?: string;
  form: FormInstance;
  drawerContent: string;
  showMarkdown: boolean;
  configText: string;
  availableTags?: string[];
  workspaces?: WorkspaceSkillSummary[];
  builtinAutoUpdateEnabled?: boolean;
  autoSyncEnabled?: boolean;
  autoSyncTargets?: string[];
  onClose: () => void;
  onSave: () => void;
  onContentChange: (content: string) => void;
  onShowMarkdownChange: (value: boolean) => void;
  onConfigTextChange: (text: string) => void;
  onChangeBuiltinLanguage?: (skill: PoolSkillDetail, language: string) => void;
  onBuiltinAutoUpdateEnabledChange?: (enabled: boolean) => void;
  onAutoSyncEnabledChange?: (enabled: boolean) => void;
  onAutoSyncTargetsChange?: (targets: string[]) => void;
  validateFrontmatter: (_: unknown, value: string) => Promise<void>;
}

export function PoolSkillDrawer({
  mode,
  activeSkill,
  loading = false,
  saving = false,
  skillName = "",
  form,
  drawerContent,
  showMarkdown,
  configText,
  availableTags = [],
  workspaces = [],
  builtinAutoUpdateEnabled = false,
  autoSyncEnabled = false,
  autoSyncTargets = [],
  onClose,
  onSave,
  onContentChange,
  onShowMarkdownChange,
  onConfigTextChange,
  onChangeBuiltinLanguage,
  onBuiltinAutoUpdateEnabledChange,
  onAutoSyncEnabledChange,
  onAutoSyncTargetsChange,
  validateFrontmatter,
}: PoolSkillDrawerProps) {
  const { t } = useTranslation();

  return (
    <Drawer
      width={520}
      placement="right"
      title={
        mode === "edit"
          ? t("skillPool.editTitle", {
              name: activeSkill?.name || skillName,
            })
          : t("skillPool.createTitle")
      }
      open={mode === "create" || mode === "edit"}
      onClose={() => {
        if (!saving) onClose();
      }}
      destroyOnHidden
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onClose} disabled={saving}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            onClick={onSave}
            loading={saving}
            disabled={loading || saving}
          >
            {mode === "edit" ? t("common.save") : t("common.create")}
          </Button>
        </div>
      }
    >
      {loading ? (
        <div style={{ padding: 24, textAlign: "center" }}>
          {t("common.loading")}
        </div>
      ) : (
        <>
          {mode === "edit" && activeSkill && (
            <div className={styles.metaStack} style={{ marginBottom: 16 }}>
              <div className={styles.infoSection}>
                <div className={styles.infoLabel}>{t("skillPool.status")}</div>
                <div
                  className={`${styles.infoBlock} ${
                    styles[getPoolBuiltinStatusTone(activeSkill.sync_status)]
                  }`}
                >
                  {getPoolBuiltinStatusLabel(activeSkill.sync_status, t)}
                </div>
              </div>
              {isSkillBuiltin(activeSkill.source) &&
                (activeSkill.available_builtin_languages?.length ?? 0) > 1 &&
                onChangeBuiltinLanguage && (
                  <div className={styles.infoSection}>
                    <div className={styles.infoLabel}>
                      {t("skillPool.builtinLanguage")}
                    </div>
                    <div className={styles.languageToggle}>
                      {activeSkill.available_builtin_languages?.map((lang) => (
                        <Button
                          key={lang}
                          size="small"
                          type={
                            activeSkill.builtin_language === lang
                              ? "primary"
                              : "default"
                          }
                          onClick={() =>
                            void onChangeBuiltinLanguage(activeSkill, lang)
                          }
                        >
                          {lang === "zh" ? "中文" : "English"}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
              <div className={styles.infoSection}>
                <div className={styles.infoLabel}>
                  {t("skillPool.installedFrom")}
                </div>
                <div className={styles.infoBlock}>
                  {activeSkill.external && activeSkill.external_path
                    ? activeSkill.external_path
                    : deriveInstalledFromLabel(activeSkill.installed_from)}
                </div>
              </div>
              <div className={styles.infoSection}>
                <div className={styles.infoLabel}>
                  {t("skillPool.automation")}
                </div>
                <div className={styles.automationPanel}>
                  {isSkillBuiltin(activeSkill.source) && (
                    <div className={styles.automationSetting}>
                      <div className={styles.automationSettingHeader}>
                        <div>
                          <div className={styles.automationSettingTitle}>
                            {t("skillPool.builtinAutoUpdate")}
                          </div>
                          <div className={styles.automationFlow}>
                            {t("skillPool.builtinAutoUpdateFlow")}
                          </div>
                        </div>
                        <Switch
                          data-testid="builtin-auto-update-switch"
                          aria-label={t("skillPool.builtinAutoUpdate")}
                          checked={builtinAutoUpdateEnabled}
                          onChange={(checked) =>
                            onBuiltinAutoUpdateEnabledChange?.(checked)
                          }
                        />
                      </div>
                    </div>
                  )}

                  <div className={styles.automationSetting}>
                    <div className={styles.automationSettingHeader}>
                      <div>
                        <div className={styles.automationSettingTitle}>
                          {t("skillPool.autoSync")}
                        </div>
                        <div className={styles.automationFlow}>
                          {t("skillPool.autoSyncFlow")}
                        </div>
                      </div>
                      <Switch
                        data-testid="auto-sync-switch"
                        aria-label={t("skillPool.autoSync")}
                        checked={autoSyncEnabled}
                        onChange={(checked) =>
                          onAutoSyncEnabledChange?.(checked)
                        }
                      />
                    </div>
                  </div>

                  {autoSyncEnabled && (
                    <div className={styles.automationTargets}>
                      <Select
                        mode="multiple"
                        style={{ width: "100%" }}
                        value={autoSyncTargets.filter((id) =>
                          workspaces.some((ws) => ws.agent_id === id),
                        )}
                        onChange={(value) =>
                          onAutoSyncTargetsChange?.(value as string[])
                        }
                        placeholder={t("skillPool.autoSyncAgentsPlaceholder")}
                        options={workspaces.map((ws) => ({
                          label: getAgentDisplayName(
                            { id: ws.agent_id, name: ws.agent_name ?? "" },
                            t,
                          ),
                          value: ws.agent_id,
                        }))}
                      />
                      <div className={styles.automationTargetsHint}>
                        {t("skillPool.autoSyncAgentsHint")}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
          <Form form={form} layout="vertical">
            <Form.Item
              name="name"
              label={t("skillPool.skillName")}
              rules={[{ required: true, message: t("skills.pleaseInputName") }]}
            >
              <Input placeholder={t("skillPool.skillNamePlaceholder")} />
            </Form.Item>

            <Form.Item
              name="content"
              rules={[{ required: true, validator: validateFrontmatter }]}
            >
              <MarkdownCopy
                content={drawerContent}
                showMarkdown={showMarkdown}
                onShowMarkdownChange={onShowMarkdownChange}
                editable={true}
                onContentChange={onContentChange}
                textareaProps={{
                  placeholder: t("skillPool.contentPlaceholder"),
                  rows: 12,
                }}
              />
            </Form.Item>

            <Form.Item
              name="tags"
              label={t("skillPool.tags")}
              rules={[
                {
                  validator: (_, value: string[] | undefined) => {
                    const bad = (value || []).find(
                      (v) => v.length > MAX_TAG_LENGTH,
                    );
                    if (bad)
                      return Promise.reject(
                        t("skillPool.tagTooLong", { max: MAX_TAG_LENGTH }),
                      );
                    return Promise.resolve();
                  },
                },
              ]}
            >
              <Select
                mode="tags"
                options={availableTags.map((tag) => ({
                  label: tag,
                  value: tag,
                }))}
                placeholder={t("skillPool.tagsPlaceholder")}
                maxCount={MAX_TAGS}
              />
            </Form.Item>

            <Form.Item label={t("skills.config")}>
              <Input.TextArea
                rows={4}
                value={configText}
                onChange={(e) => {
                  onConfigTextChange(e.target.value);
                }}
                placeholder={t("skills.configPlaceholder")}
              />
            </Form.Item>
          </Form>
        </>
      )}
    </Drawer>
  );
}
