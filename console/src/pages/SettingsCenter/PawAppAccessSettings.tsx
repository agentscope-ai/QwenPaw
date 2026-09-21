import {
  Alert,
  Button,
  Collapse,
  Empty,
  Select,
  Spin,
  Switch,
  Tag,
  App as AntApp,
} from "antd";
import { AppWindow, RefreshCw, Save, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  pawappGrantsApi,
  type PawAppGrantAction,
  type PawAppGrantCapability,
  type PawAppGrantCatalog,
} from "@/api/modules/pawappGrants";
import { useAgentStore } from "@/stores/agentStore";
import settingsStyles from "./index.module.less";
import styles from "./PawAppAccessSettings.module.less";

interface GrantDraft {
  enabled: boolean;
  inputValues: Record<string, string[]>;
}

function actionKey(action: PawAppGrantAction): string {
  return `${action.app_id}:${action.action_id}`;
}

function capabilityKey(capability: PawAppGrantCapability): string {
  return `${capability.app_id}:${capability.capability_id}`;
}

function draftFor(action: PawAppGrantAction): GrantDraft {
  return {
    enabled: action.enabled,
    inputValues: Object.fromEntries(
      Object.entries(action.input_values).map(([key, values]) => [
        key,
        [...values],
      ]),
    ),
  };
}

function stringInputs(action: PawAppGrantAction) {
  return Object.entries(action.input_schema.properties ?? {}).flatMap(
    ([name, schema]) => {
      if (
        !schema ||
        typeof schema !== "object" ||
        Array.isArray(schema) ||
        !("type" in schema) ||
        schema.type !== "string"
      ) {
        return [];
      }
      return [
        [
          name,
          schema as { type: "string"; title?: string; description?: string },
        ],
      ] as const;
    },
  );
}

export default function PawAppAccessSettings() {
  const { t } = useTranslation();
  const { message } = AntApp.useApp();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const [catalog, setCatalog] = useState<PawAppGrantCatalog | null>(null);
  const [drafts, setDrafts] = useState<Record<string, GrantDraft>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    void pawappGrantsApi
      .list(selectedAgent, controller.signal)
      .then((next) => {
        setCatalog(next);
        setDrafts(
          Object.fromEntries(
            next.actions.map((action) => [actionKey(action), draftFor(action)]),
          ),
        );
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setLoadError(
          error instanceof Error ? error.message : "Unable to load App access",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selectedAgent, reloadToken]);

  const appSections = useMemo(() => {
    const groups = new Map<
      string,
      { actions: PawAppGrantAction[]; capabilities: PawAppGrantCapability[] }
    >();
    for (const action of catalog?.actions ?? []) {
      const group = groups.get(action.app_id) ?? {
        actions: [],
        capabilities: [],
      };
      group.actions.push(action);
      groups.set(action.app_id, group);
    }
    for (const capability of catalog?.capabilities ?? []) {
      const group = groups.get(capability.app_id) ?? {
        actions: [],
        capabilities: [],
      };
      group.capabilities.push(capability);
      groups.set(capability.app_id, group);
    }
    return [...groups.entries()];
  }, [catalog]);

  const applyCatalog = (next: PawAppGrantCatalog) => {
    setCatalog(next);
    setDrafts(
      Object.fromEntries(
        next.actions.map((action) => [actionKey(action), draftFor(action)]),
      ),
    );
  };

  const saveCapability = async (
    capability: PawAppGrantCapability,
    enabled: boolean,
  ) => {
    if (!catalog) return;
    const key = capabilityKey(capability);
    setSaving(`capability:${key}`);
    try {
      const next = await pawappGrantsApi.updateCapability(
        selectedAgent,
        capability.app_id,
        capability.capability_id,
        { expected_revision: catalog.revision, enabled },
      );
      applyCatalog(next);
      message.success(
        enabled
          ? t("settingsCenter.appCapabilityGranted", "Capability enabled")
          : t("settingsCenter.appCapabilityRevoked", "Capability disabled"),
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("settingsCenter.appAccessSaveFailed", "Could not save access"),
      );
      setReloadToken((value) => value + 1);
    } finally {
      setSaving(null);
    }
  };

  const changeDraft = (
    action: PawAppGrantAction,
    update: (current: GrantDraft) => GrantDraft,
  ) => {
    const key = actionKey(action);
    setDrafts((current) => ({
      ...current,
      [key]: update(current[key] ?? draftFor(action)),
    }));
  };

  const save = async (action: PawAppGrantAction) => {
    if (!catalog) return;
    const key = actionKey(action);
    const draft = drafts[key] ?? draftFor(action);
    setSaving(key);
    try {
      const next = await pawappGrantsApi.update(
        selectedAgent,
        action.app_id,
        action.action_id,
        {
          expected_revision: catalog.revision,
          enabled: draft.enabled,
          input_values: draft.enabled ? draft.inputValues : {},
        },
      );
      applyCatalog(next);
      message.success(
        draft.enabled
          ? t("settingsCenter.appAccessGranted", "App action enabled")
          : t("settingsCenter.appAccessRevoked", "App action disabled"),
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("settingsCenter.appAccessSaveFailed", "Could not save access"),
      );
      setReloadToken((value) => value + 1);
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return (
      <div className={styles.loading}>
        <Spin tip={t("common.loading")} />
      </div>
    );
  }

  return (
    <div className={settingsStyles.preferencePage}>
      <div className={`${settingsStyles.pageTitle} ${styles.title}`}>
        <div>
          <h2>{t("settingsCenter.pages.appAccess", "App access")}</h2>
          <p>
            {t(
              "settingsCenter.appAccessDescription",
              "Choose which registered App actions the selected agent may run.",
            )}
          </p>
        </div>
        <Button
          icon={<RefreshCw size={15} />}
          onClick={() => setReloadToken((value) => value + 1)}
        >
          {t("common.refresh", "Refresh")}
        </Button>
      </div>

      {loadError && (
        <Alert
          className={styles.alert}
          type="error"
          showIcon
          message={t(
            "settingsCenter.appAccessLoadFailed",
            "App access could not be loaded",
          )}
          description={loadError}
        />
      )}

      {!loadError && appSections.length === 0 && (
        <div className={styles.empty}>
          <Empty
            description={t(
              "settingsCenter.appAccessEmpty",
              "No active App actions are registered.",
            )}
          />
        </div>
      )}

      {appSections.map(([appId, section]) => (
        <section
          key={appId}
          className={`${settingsStyles.settingsSection} ${styles.appPanel}`}
        >
          <header className={styles.appPanelHeader}>
            <div className={styles.appIdentity}>
              <span className={styles.appIcon}>
                <AppWindow size={18} />
              </span>
              <div>
                <h3>{appId}</h3>
                <span>
                  {t("settingsCenter.appPanelScope", "Main Chat access")}
                </span>
              </div>
            </div>
            <Tag>
              {t("settingsCenter.appPanelCapabilityCount", {
                count: section.capabilities.length,
                defaultValue: `${section.capabilities.length} capabilities`,
              })}
            </Tag>
          </header>
          <div className={styles.appPanelBody}>
            {section.capabilities.length > 0 && (
              <div className={settingsStyles.settingsCard}>
                <div className={styles.capabilityIntro}>
                  <strong>
                    {t(
                      "settingsCenter.appCapabilitiesTitle",
                      "Main Chat capabilities",
                    )}
                  </strong>
                  <span>
                    {t(
                      "settingsCenter.appCapabilitiesHint",
                      "Choose what this agent may do. Changes apply to the whole capability bundle.",
                    )}
                  </span>
                </div>
                {section.capabilities.map((capability) => {
                  const key = capabilityKey(capability);
                  const riskLabel =
                    capability.risk === "generation"
                      ? t(
                          "settingsCenter.appCapabilityGeneration",
                          "Generation",
                        )
                      : capability.risk === "analysis"
                      ? t("settingsCenter.appCapabilityAnalysis", "Analysis")
                      : capability.risk === "write"
                      ? t("settingsCenter.appCapabilityWrite", "Writes")
                      : capability.risk === "read"
                      ? t("settingsCenter.appCapabilityRead", "Read-only")
                      : t("settingsCenter.appCapabilityOther", "Action");
                  return (
                    <article key={key} className={styles.capability}>
                      <div className={styles.actionHeader}>
                        <span className={settingsStyles.settingIcon}>
                          <ShieldCheck size={18} />
                        </span>
                        <div className={styles.actionCopy}>
                          <div className={styles.actionName}>
                            <strong>{capability.label}</strong>
                            <Tag
                              color={
                                capability.risk === "read" ? "green" : "orange"
                              }
                            >
                              {riskLabel}
                            </Tag>
                            {capability.partial && (
                              <Tag color="warning">
                                {t(
                                  "settingsCenter.appCapabilityPartial",
                                  "Partially enabled",
                                )}
                              </Tag>
                            )}
                            {capability.stale && (
                              <Tag color="warning">
                                {t(
                                  "settingsCenter.appAccessChanged",
                                  "Review changed action",
                                )}
                              </Tag>
                            )}
                          </div>
                          <p>{capability.summary}</p>
                        </div>
                        <Switch
                          aria-label={`${capability.label} access`}
                          checked={capability.enabled}
                          loading={saving === `capability:${key}`}
                          disabled={
                            saving !== null && saving !== `capability:${key}`
                          }
                          onChange={(enabled) =>
                            void saveCapability(capability, enabled)
                          }
                        />
                      </div>
                      <div className={styles.tags}>
                        <Tag>
                          {t("settingsCenter.appCapabilityActionCount", {
                            count: capability.action_ids.length,
                            defaultValue: `${capability.action_ids.length} actions`,
                          })}
                        </Tag>
                        {capability.effects.map((effect) => (
                          <Tag key={effect} color="orange">
                            {effect}
                          </Tag>
                        ))}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}

            {section.actions.length > 0 && (
              <Collapse
                className={styles.advanced}
                items={[
                  {
                    key: "advanced",
                    label: t(
                      "settingsCenter.appAdvancedTitle",
                      "Advanced action limits",
                    ),
                    children: (
                      <div className={settingsStyles.settingsCard}>
                        <div className={styles.advancedHint}>
                          {t(
                            "settingsCenter.appAdvancedHint",
                            "Use this view only for resource selectors and exact action-level limits.",
                          )}
                        </div>
                        {section.actions.map((action) => {
                          const key = actionKey(action);
                          const draft = drafts[key] ?? draftFor(action);
                          const inputs = stringInputs(action);
                          return (
                            <article key={key} className={styles.action}>
                              <div className={styles.actionHeader}>
                                <span className={settingsStyles.settingIcon}>
                                  <ShieldCheck size={18} />
                                </span>
                                <div className={styles.actionCopy}>
                                  <div className={styles.actionName}>
                                    <strong>{action.action_id}</strong>
                                    {action.stale && (
                                      <Tag color="warning">
                                        {t(
                                          "settingsCenter.appAccessChanged",
                                          "Review changed action",
                                        )}
                                      </Tag>
                                    )}
                                  </div>
                                  <p>{action.summary}</p>
                                </div>
                                <Switch
                                  aria-label={`${action.action_id} access`}
                                  checked={draft.enabled}
                                  onChange={(enabled) =>
                                    changeDraft(action, (current) => ({
                                      ...current,
                                      enabled,
                                    }))
                                  }
                                />
                              </div>

                              <div className={styles.tags}>
                                {action.permissions.map((permission) => (
                                  <Tag key={permission}>{permission}</Tag>
                                ))}
                                {action.effects.map((effect) => (
                                  <Tag key={effect} color="orange">
                                    {effect}
                                  </Tag>
                                ))}
                              </div>

                              {draft.enabled && inputs.length > 0 && (
                                <div className={styles.constraints}>
                                  <div className={styles.constraintHeading}>
                                    <strong>
                                      {t(
                                        "settingsCenter.appAccessLimits",
                                        "Exact input limits",
                                      )}
                                    </strong>
                                    <span>
                                      {t(
                                        "settingsCenter.appAccessLimitsHint",
                                        "Leave every field empty to allow all valid inputs.",
                                      )}
                                    </span>
                                  </div>
                                  <div className={styles.constraintGrid}>
                                    {inputs.map(([inputName, schema]) => (
                                      <label key={inputName}>
                                        <span>{schema.title || inputName}</span>
                                        <Select
                                          aria-label={`${action.action_id} ${inputName} limits`}
                                          mode="tags"
                                          value={
                                            draft.inputValues[inputName] ?? []
                                          }
                                          tokenSeparators={[","]}
                                          placeholder={t(
                                            "settingsCenter.appAccessAnyValue",
                                            "Any value",
                                          )}
                                          onChange={(values) =>
                                            changeDraft(action, (current) => {
                                              const inputValues = {
                                                ...current.inputValues,
                                              };
                                              if (values.length > 0) {
                                                inputValues[inputName] = values;
                                              } else {
                                                delete inputValues[inputName];
                                              }
                                              return {
                                                ...current,
                                                inputValues,
                                              };
                                            })
                                          }
                                        />
                                      </label>
                                    ))}
                                  </div>
                                </div>
                              )}

                              <div className={styles.actionFooter}>
                                <code>
                                  {action.descriptor_digest.slice(0, 12)}
                                </code>
                                <Button
                                  type="primary"
                                  icon={<Save size={15} />}
                                  loading={saving === key}
                                  disabled={saving !== null && saving !== key}
                                  onClick={() => void save(action)}
                                >
                                  {t("common.save", "Save")}
                                </Button>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    ),
                  },
                ]}
                defaultActiveKey={
                  section.capabilities.length > 0 ? [] : ["advanced"]
                }
              />
            )}
          </div>
        </section>
      ))}
    </div>
  );
}
