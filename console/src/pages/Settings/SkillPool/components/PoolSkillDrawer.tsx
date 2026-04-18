import { Button, Drawer, Form, Input, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
  isSkillBuiltin,
} from "@/utils/skill";
import { MAX_TAGS, MAX_TAG_LENGTH } from "../../../Agent/Skills/components";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import type { PoolMode } from "../useSkillPool";
import styles from "../index.module.less";

type FormInstance = ReturnType<typeof Form.useForm>[0];

interface PoolSkillDrawerProps {
  mode: PoolMode | null;
  activeSkill: PoolSkillSpec | null;
  form: FormInstance;
  drawerContent: string;
  showMarkdown: boolean;
  configText: string;
  availableTags?: string[];
  onClose: () => void;
  onSave: () => void;
  onContentChange: (content: string) => void;
  onShowMarkdownChange: (value: boolean) => void;
  onConfigTextChange: (text: string) => void;
  onChangeBuiltinLanguage?: (skill: PoolSkillSpec, language: string) => void;
  validateFrontmatter: (_: unknown, value: string) => Promise<void>;
}

export function PoolSkillDrawer({
  mode,
  activeSkill,
  form,
  drawerContent,
  showMarkdown,
  configText,
  availableTags = [],
  onClose,
  onSave,
  onContentChange,
  onShowMarkdownChange,
  onConfigTextChange,
  onChangeBuiltinLanguage,
  validateFrontmatter,
}: PoolSkillDrawerProps) {
  const { t } = useTranslation();

  return (
    <Drawer
      width={520}
      placement="right"
      title={
        mode === "edit"
          ? t("skillPool.editTitle", { name: activeSkill?.name || "" })
          : t("skillPool.createTitle")
      }
      open={mode === "create" || mode === "edit"}
      onClose={onClose}
      destroyOnClose
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="primary" onClick={onSave}>
            {mode === "edit" ? t("common.save") : t("common.create")}
          </Button>
        </div>
      }
    >
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
    </Drawer>
  );
}
