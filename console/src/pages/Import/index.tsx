import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Collapse,
  Empty,
  Modal,
  Pagination,
  Progress,
  Spin,
  Steps,
  Tag,
  Tooltip,
} from "antd";
import { CheckCircle2, CircleAlert, Download, PackageOpen } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import type {
  ImportAssetResult,
  ImportAssetState,
  ImportProviderSnapshot,
  ImportSelection,
  ImportSource,
} from "../../api/types/import";
import { useImportJob } from "./useImportJob";
import styles from "./index.module.less";

const GROUPS = ["memory", "cron", "skill", "mcp", "plugin"] as const;
const ASSET_PAGE_SIZE = 100;
const FIELDS = {
  memory: "memory",
  cron: "cron",
  skill: "skills",
  mcp: "mcp",
  plugin: "plugins",
} as const;
const COLORS: Record<ImportAssetState, string> = {
  pending: "default",
  repairing: "processing",
  ready: "success",
  failed: "error",
  succeeded: "success",
  existing: "warning",
};

type RetryAsset = {
  provider: ImportProviderSnapshot;
  asset: ImportAssetResult;
};

const retryKey = ({ provider, asset }: RetryAsset) =>
  `${provider.source}:${asset.asset_type}:${asset.source_id}`;

function retrySelection(items: RetryAsset[]) {
  return items.reduce<Partial<Record<ImportSource, ImportSelection>>>(
    (selection, { provider, asset }) => {
      const source = (selection[provider.source] ??= { sessions: false });
      const field = FIELDS[asset.asset_type];
      source[field] = [...(source[field] ?? []), asset.source_id];
      return selection;
    },
    {},
  );
}

function AssetStatus({ asset }: { asset: ImportAssetResult }) {
  const { t } = useTranslation();
  const state = asset.state;
  const fallback =
    asset.state === "failed"
      ? t("portabilityImport.hints.failed")
      : asset.state === "succeeded" && asset.enabled === false
      ? t(
          asset.asset_type === "cron"
            ? "portabilityImport.hints.cronReview"
            : "portabilityImport.hints.disabled",
        )
      : "";
  const tag = (
    <Tag color={COLORS[asset.state]}>
      {t(`portabilityImport.states.${state}`)}
    </Tag>
  );
  return asset.message || fallback ? (
    <Tooltip title={asset.message || fallback}>{tag}</Tooltip>
  ) : (
    tag
  );
}

const conversationsDone = (provider: ImportProviderSnapshot) =>
  provider.sessions_total > 0 &&
  provider.sessions_processed >= provider.sessions_total;

function ConversationStatus({
  provider,
}: {
  provider: ImportProviderSnapshot;
}) {
  const { t } = useTranslation();
  if (provider.state === "failed") {
    return (
      <Tag color="error">{t("portabilityImport.sessionStates.failed")}</Tag>
    );
  }
  if (provider.state === "completed" || conversationsDone(provider)) {
    return (
      <Tag color="success">
        {t("portabilityImport.sessionStates.succeeded", {
          count: provider.sessions_imported,
          total: provider.sessions_total,
        })}
      </Tag>
    );
  }
  return (
    <Tag color="processing">
      {t("portabilityImport.sessionStates.importing", {
        count: provider.sessions_processed,
        total: provider.sessions_total,
      })}
    </Tag>
  );
}

function completion(providers: ImportProviderSnapshot[]) {
  const assets = providers.flatMap((provider) => provider.assets);
  const sessionRows = providers.filter(
    (provider) => provider.selection.sessions && provider.sessions_total,
  );
  const doneAssets = assets.reduce(
    (total, asset) =>
      total +
      (["failed", "succeeded"].includes(asset.state)
        ? 1
        : asset.state === "ready"
        ? 0.5
        : 0),
    0,
  );
  const doneSessions = sessionRows.filter(
    (provider) =>
      ["completed", "failed"].includes(provider.state) ||
      conversationsDone(provider),
  ).length;
  const total = assets.length + sessionRows.length;
  return total ? Math.round(((doneAssets + doneSessions) / total) * 100) : 0;
}

export default function ImportPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const {
    sources,
    job,
    selectedAgent,
    loading,
    error,
    detect,
    scan,
    start,
    retry,
    cancel,
    reset,
  } = useImportJob();
  const [sourceSelections, setSourceSelections] = useState<
    Record<string, ImportSource[]>
  >({});
  const selectedSources = sourceSelections[selectedAgent] ?? [];
  const [selections, setSelections] = useState<
    Record<string, Partial<Record<ImportSource, ImportSelection>>>
  >({});
  const [retryKeys, setRetryKeys] = useState<Record<string, string[]>>({});
  const [confirmRetry, setConfirmRetry] = useState(false);
  const [pluginAction, setPluginAction] = useState<"start" | "retry" | null>(
    null,
  );
  const [pluginConfirmed, setPluginConfirmed] = useState(false);
  const [assetPages, setAssetPages] = useState<Record<string, number>>({});
  const selectionKey = job?.job_id ?? "";
  const currentSelections = useMemo(
    () => selections[selectionKey] ?? {},
    [selectionKey, selections],
  );

  const updateSources = useCallback(
    (update: (sources: ImportSource[]) => ImportSource[]) =>
      setSourceSelections((current) => ({
        ...current,
        [selectedAgent]: update(current[selectedAgent] ?? []),
      })),
    [selectedAgent],
  );

  useEffect(() => {
    void detect().catch(() => undefined);
  }, [detect]);
  useEffect(() => {
    if (!job && sources.length && !sourceSelections[selectedAgent]) {
      updateSources(() =>
        sources
          .filter((source) => source.detected)
          .map((source) => source.source),
      );
    }
  }, [job, selectedAgent, sourceSelections, sources, updateSources]);
  useEffect(() => {
    if (
      job?.state !== "awaiting_selection" ||
      !selectionKey ||
      Object.keys(currentSelections).length
    ) {
      return;
    }
    setSelections((current) => ({
      ...current,
      [selectionKey]: Object.fromEntries(
        job.providers
          .filter((provider) => provider.state === "ready")
          .map((provider) => [provider.source, provider.selection]),
      ),
    }));
  }, [currentSelections, job, selectionKey]);
  useEffect(() => {
    setConfirmRetry(false);
    setPluginAction(null);
    setPluginConfirmed(false);
  }, [selectionKey]);

  const current = !job ? 0 : job.state === "awaiting_selection" ? 1 : 2;
  const isDone = Boolean(
    job &&
      ["completed", "completed_with_issues", "failed", "interrupted"].includes(
        job.state,
      ),
  );
  const isCancelling = job?.state === "cancelling";
  const percent = useMemo(() => completion(job?.providers ?? []), [job]);

  const updateSelection = (
    source: ImportSource,
    update: (selection: ImportSelection) => ImportSelection,
  ) => {
    if (!selectionKey) return;
    setSelections((current) => ({
      ...current,
      [selectionKey]: {
        ...current[selectionKey],
        [source]: update(current[selectionKey]?.[source] ?? {}),
      },
    }));
  };

  const failedAssets = useMemo<RetryAsset[]>(
    () =>
      job?.providers.flatMap((provider) =>
        provider.assets
          .filter((asset) => asset.state === "failed")
          .map((asset) => ({ provider, asset })),
      ) ?? [],
    [job],
  );
  const selectedRetryKeySet = useMemo(
    () => new Set(retryKeys[selectionKey] ?? []),
    [retryKeys, selectionKey],
  );
  const selectedRetryAssets = failedAssets.filter(({ provider, asset }) =>
    selectedRetryKeySet.has(retryKey({ provider, asset })),
  );
  const selectedPluginNames = useMemo(
    () =>
      job?.providers.flatMap((provider) => {
        const selected = new Set(
          currentSelections[provider.source]?.plugins ?? [],
        );
        return provider.assets
          .filter(
            (asset) =>
              asset.asset_type === "plugin" && selected.has(asset.source_id),
          )
          .map((asset) => asset.name);
      }) ?? [],
    [currentSelections, job],
  );
  const retryPluginNames = selectedRetryAssets
    .filter(({ asset }) => asset.asset_type === "plugin")
    .map(({ asset }) => asset.name);
  const hasSelection = Object.values(currentSelections).some(
    (selection) =>
      selection.sessions ||
      GROUPS.some((type) => Boolean(selection[FIELDS[type]]?.length)),
  );
  const toggleRetry = (item: RetryAsset, checked: boolean) => {
    if (!selectionKey) return;
    const key = retryKey(item);
    setRetryKeys((current) => {
      const keys = new Set(current[selectionKey]);
      if (checked) keys.add(key);
      else keys.delete(key);
      return { ...current, [selectionKey]: [...keys] };
    });
  };
  const toggleAllRetries = (checked: boolean) =>
    setRetryKeys((current) => ({
      ...current,
      [selectionKey]: checked ? failedAssets.map(retryKey) : [],
    }));
  const runRetry = async (allowPluginExecution = false) => {
    const key = selectionKey;
    if (!selectedRetryAssets.length) return;
    if (retryPluginNames.length && !allowPluginExecution) {
      setConfirmRetry(false);
      setPluginConfirmed(false);
      setPluginAction("retry");
      return;
    }
    const selection = retrySelection(selectedRetryAssets);
    await retry(selection, allowPluginExecution);
    setRetryKeys((current) =>
      Object.fromEntries(Object.entries(current).filter(([id]) => id !== key)),
    );
    setConfirmRetry(false);
  };
  const startImport = () => {
    if (selectedPluginNames.length) {
      setPluginConfirmed(false);
      setPluginAction("start");
      return;
    }
    void start(currentSelections);
  };
  const confirmPluginAction = async () => {
    if (pluginAction === "start") await start(currentSelections, true);
    else if (pluginAction === "retry") await runRetry(true);
    setPluginAction(null);
    setPluginConfirmed(false);
  };
  const pluginNames =
    pluginAction === "retry" ? retryPluginNames : selectedPluginNames;
  const abandon = async () => {
    try {
      if ((await cancel()).state === "interrupted") reset();
    } catch {
      // The hook keeps the error visible.
    }
  };

  const toggleAsset = (
    provider: ImportProviderSnapshot,
    asset: ImportAssetResult,
    checked: boolean,
  ) => {
    const field = FIELDS[asset.asset_type];
    updateSelection(provider.source, (selection) => {
      const values = new Set(selection[field] ?? []);
      if (checked) values.add(asset.source_id);
      else values.delete(asset.source_id);
      return { ...selection, [field]: [...values] };
    });
  };

  const toggleGroup = (
    provider: ImportProviderSnapshot,
    type: (typeof GROUPS)[number],
    checked: boolean,
  ) => {
    const field = FIELDS[type];
    const ids = provider.assets
      .filter((asset) => asset.asset_type === type)
      .map((asset) => asset.source_id);
    updateSelection(provider.source, (selection) => ({
      ...selection,
      [field]: checked ? ids : [],
    }));
  };

  const toggleTools = (provider: ImportProviderSnapshot, checked: boolean) =>
    updateSelection(provider.source, (selection) => ({
      ...selection,
      ...Object.fromEntries(
        GROUPS.map((type) => [
          FIELDS[type],
          checked
            ? provider.assets
                .filter((asset) => asset.asset_type === type)
                .map((asset) => asset.source_id)
            : [],
        ]),
      ),
    }));

  const assetPage = (key: string) => assetPages[key] ?? 1;
  const setAssetPage = (key: string, page: number) =>
    setAssetPages((current) => ({ ...current, [key]: page }));

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.marketplace")}
        current={t("portabilityImport.title")}
      />
      <main className={styles.content}>
        <div className={styles.intro}>
          <Download size={28} />
          <div>
            <h2>{t("portabilityImport.title")}</h2>
            <p>{t("portabilityImport.description")}</p>
          </div>
        </div>
        {job && (
          <Alert
            type={job.agent_id === selectedAgent ? "info" : "warning"}
            showIcon
            message={t("portabilityImport.targetAgent", {
              agent: job.agent_id,
            })}
          />
        )}
        <Steps
          current={current}
          items={[
            { title: t("portabilityImport.steps.sources") },
            { title: t("portabilityImport.steps.inventory") },
            { title: t("portabilityImport.steps.progress") },
          ]}
        />
        {error && <Alert type="error" showIcon message={error} />}
        {job && !isDone && (
          <div className={styles.actions}>
            <Button
              danger
              disabled={isCancelling}
              loading={loading}
              onClick={() => void abandon()}
            >
              {t(
                isCancelling ? "portabilityImport.cancelling" : "common.cancel",
              )}
            </Button>
          </div>
        )}

        {!job && (
          <section className={styles.section}>
            <div className={styles.sectionHeading}>
              <h3>{t("portabilityImport.chooseSources")}</h3>
              <p>{t("portabilityImport.chooseSourcesHint")}</p>
            </div>
            {loading && !sources.length ? (
              <div className={styles.center}>
                <Spin />
              </div>
            ) : (
              <div className={styles.sourceGrid}>
                {sources.map((source) => (
                  <Card key={source.source} className={styles.sourceCard}>
                    <Checkbox
                      checked={selectedSources.includes(source.source)}
                      disabled={!source.detected}
                      onChange={(event) =>
                        updateSources((selected) =>
                          event.target.checked
                            ? [...selected, source.source]
                            : selected.filter((item) => item !== source.source),
                        )
                      }
                    >
                      <strong>{source.name}</strong>
                    </Checkbox>
                    <Tag color={source.detected ? "success" : "default"}>
                      {t(
                        source.detected
                          ? "portabilityImport.detected"
                          : "portabilityImport.notDetected",
                      )}
                    </Tag>
                  </Card>
                ))}
              </div>
            )}
            {!loading && sources.every((source) => !source.detected) && (
              <Empty description={t("portabilityImport.noSources")} />
            )}
            <div className={styles.actions}>
              <Button
                type="primary"
                disabled={!selectedSources.length}
                loading={loading}
                onClick={() => void scan(selectedSources)}
              >
                {t("portabilityImport.continue")}
              </Button>
            </div>
          </section>
        )}

        {job?.state === "scanning" && (
          <div className={styles.center}>
            <Spin size="large" />
            <span>{t("portabilityImport.scanning")}</span>
          </div>
        )}

        {job?.state === "awaiting_selection" && (
          <section className={styles.section}>
            <div className={styles.sectionHeading}>
              <h3>{t("portabilityImport.chooseContent")}</h3>
              <p>{t("portabilityImport.defaultSelected")}</p>
            </div>
            {job.providers.map((provider) => (
              <Card key={provider.source} title={provider.source.toUpperCase()}>
                {provider.state === "failed" ? (
                  <Alert type="error" showIcon message={provider.error} />
                ) : (
                  <>
                    <div className={styles.row}>
                      <Checkbox
                        checked={
                          currentSelections[provider.source]?.sessions ?? false
                        }
                        disabled={!provider.sessions_total}
                        onChange={(event) =>
                          updateSelection(provider.source, (selection) => ({
                            ...selection,
                            sessions: event.target.checked,
                          }))
                        }
                      >
                        {t("portabilityImport.conversations")}
                      </Checkbox>
                      <span>
                        {t("portabilityImport.items", {
                          count: provider.sessions_total,
                        })}
                      </span>
                    </div>
                    {provider.assets.length > 0 &&
                      (() => {
                        const selectedIds = new Set(
                          GROUPS.flatMap((type) =>
                            (
                              currentSelections[provider.source]?.[
                                FIELDS[type]
                              ] ?? []
                            ).map((id) => `${type}:${id}`),
                          ),
                        );
                        const selected = provider.assets.filter((asset) =>
                          selectedIds.has(
                            `${asset.asset_type}:${asset.source_id}`,
                          ),
                        ).length;
                        return (
                          <div className={styles.row}>
                            <Checkbox
                              checked={selected === provider.assets.length}
                              indeterminate={Boolean(
                                selected && selected < provider.assets.length,
                              )}
                              onChange={(event) =>
                                toggleTools(provider, event.target.checked)
                              }
                            >
                              {t("portabilityImport.toolsSetup")}
                            </Checkbox>
                            <span>
                              {t("portabilityImport.items", {
                                count: provider.assets.length,
                              })}
                            </span>
                          </div>
                        );
                      })()}
                    <Collapse
                      className={styles.groups}
                      defaultActiveKey={[...GROUPS]}
                      items={GROUPS.flatMap((type) => {
                        const assets = provider.assets.filter(
                          (asset) => asset.asset_type === type,
                        );
                        if (!assets.length) return [];
                        const field = FIELDS[type];
                        const selected = new Set(
                          currentSelections[provider.source]?.[field] ?? [],
                        );
                        const pageKey = `select:${provider.source}:${type}`;
                        const page = assetPage(pageKey);
                        const pageAssets = assets.slice(
                          (page - 1) * ASSET_PAGE_SIZE,
                          page * ASSET_PAGE_SIZE,
                        );
                        return [
                          {
                            key: type,
                            label: (
                              <Checkbox
                                checked={selected.size === assets.length}
                                indeterminate={Boolean(
                                  selected.size &&
                                    selected.size < assets.length,
                                )}
                                onClick={(event) => event.stopPropagation()}
                                onChange={(event) =>
                                  toggleGroup(
                                    provider,
                                    type,
                                    event.target.checked,
                                  )
                                }
                              >
                                {t(`portabilityImport.groups.${type}`)} (
                                {assets.length})
                              </Checkbox>
                            ),
                            children: (
                              <>
                                {pageAssets.map((asset) => (
                                  <div
                                    className={styles.assetRow}
                                    key={asset.source_id}
                                  >
                                    <Tooltip
                                      title={
                                        asset.requires_sessions
                                          ? t(
                                              "portabilityImport.heartbeatRequiresSessions",
                                            )
                                          : undefined
                                      }
                                    >
                                      <Checkbox
                                        checked={selected.has(asset.source_id)}
                                        onChange={(event) =>
                                          toggleAsset(
                                            provider,
                                            asset,
                                            event.target.checked,
                                          )
                                        }
                                      >
                                        {asset.name}
                                      </Checkbox>
                                    </Tooltip>
                                  </div>
                                ))}
                                {assets.length > ASSET_PAGE_SIZE && (
                                  <Pagination
                                    current={page}
                                    pageSize={ASSET_PAGE_SIZE}
                                    size="small"
                                    total={assets.length}
                                    onChange={(next) =>
                                      setAssetPage(pageKey, next)
                                    }
                                  />
                                )}
                              </>
                            ),
                          },
                        ];
                      })}
                    />
                  </>
                )}
              </Card>
            ))}
            <div className={styles.actions}>
              <Button
                type="primary"
                disabled={!hasSelection}
                loading={loading}
                onClick={startImport}
              >
                {t("portabilityImport.start")}
              </Button>
            </div>
          </section>
        )}

        {job && current === 2 && (
          <section className={styles.section}>
            <div>
              <Progress
                percent={isDone ? 100 : percent}
                status={job.state === "failed" ? "exception" : "active"}
              />
            </div>
            <div className={styles.resultHeader}>
              {isDone ? <CheckCircle2 /> : <PackageOpen />}
              <div>
                <h3>
                  {t(
                    isDone
                      ? "portabilityImport.finished"
                      : isCancelling
                      ? "portabilityImport.cancelling"
                      : "portabilityImport.importing",
                  )}
                </h3>
                <p>
                  {t(
                    isCancelling
                      ? "portabilityImport.cancellingHint"
                      : "portabilityImport.keepOpen",
                  )}
                </p>
              </div>
            </div>
            {job.providers.map((provider) => (
              <Card key={provider.source} title={provider.source.toUpperCase()}>
                {provider.selection.sessions && provider.sessions_total > 0 && (
                  <div className={styles.row}>
                    <span>{t("portabilityImport.conversations")}</span>
                    <ConversationStatus provider={provider} />
                  </div>
                )}
                {provider.assets
                  .slice(
                    (assetPage(`result:${provider.source}`) - 1) *
                      ASSET_PAGE_SIZE,
                    assetPage(`result:${provider.source}`) * ASSET_PAGE_SIZE,
                  )
                  .map((asset) => (
                    <div
                      className={styles.assetRow}
                      key={`${asset.asset_type}:${asset.source_id}`}
                    >
                      <span>{asset.name}</span>
                      <AssetStatus asset={asset} />
                      {asset.state === "failed" && (
                        <Checkbox
                          aria-label={asset.name}
                          checked={selectedRetryKeySet.has(
                            retryKey({ provider, asset }),
                          )}
                          disabled={!isDone}
                          onChange={(event) =>
                            toggleRetry(
                              { provider, asset },
                              event.target.checked,
                            )
                          }
                        />
                      )}
                    </div>
                  ))}
                {provider.assets.length > ASSET_PAGE_SIZE && (
                  <Pagination
                    current={assetPage(`result:${provider.source}`)}
                    pageSize={ASSET_PAGE_SIZE}
                    size="small"
                    total={provider.assets.length}
                    onChange={(next) =>
                      setAssetPage(`result:${provider.source}`, next)
                    }
                  />
                )}
                {provider.error && (
                  <Alert
                    icon={<CircleAlert />}
                    type="error"
                    showIcon
                    message={provider.error}
                  />
                )}
              </Card>
            ))}
            {job.logs.length > 0 && (
              <Collapse
                items={[
                  {
                    key: "logs",
                    label: t("portabilityImport.details"),
                    children: (
                      <pre className={styles.logs}>{job.logs.join("\n")}</pre>
                    ),
                  },
                ]}
              />
            )}
            <div className={styles.actions}>
              {isDone && failedAssets.length > 0 && (
                <>
                  <Checkbox
                    checked={selectedRetryAssets.length === failedAssets.length}
                    indeterminate={Boolean(
                      selectedRetryAssets.length &&
                        selectedRetryAssets.length < failedAssets.length,
                    )}
                    onChange={(event) => toggleAllRetries(event.target.checked)}
                  >
                    {t("portabilityImport.selectAllFailed")}
                  </Checkbox>
                  <Button
                    disabled={!selectedRetryAssets.length || loading}
                    loading={loading}
                    onClick={() => setConfirmRetry(true)}
                  >
                    {t("portabilityImport.retrySelected", {
                      count: selectedRetryAssets.length,
                    })}
                  </Button>
                </>
              )}
              <Button
                type="primary"
                disabled={!isDone}
                onClick={() => {
                  reset();
                  navigate("/chat");
                }}
              >
                {t("portabilityImport.done")}
              </Button>
            </div>
          </section>
        )}
        <Modal
          open={confirmRetry}
          title={t("common.retry")}
          okText={t("common.retry")}
          cancelText={t("common.cancel")}
          onCancel={() => setConfirmRetry(false)}
          onOk={() => void runRetry()}
        >
          {t("portabilityImport.retryConfirm", {
            count: selectedRetryAssets.length,
          })}
        </Modal>
        <Modal
          open={Boolean(pluginAction)}
          title={t("portabilityImport.pluginWarningTitle")}
          okText={t("portabilityImport.pluginWarningAction")}
          cancelText={t("common.cancel")}
          okButtonProps={{ disabled: !pluginConfirmed }}
          onCancel={() => setPluginAction(null)}
          onOk={() => void confirmPluginAction()}
        >
          <p>{t("portabilityImport.pluginWarning")}</p>
          <ul>
            {pluginNames.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
          <Checkbox
            checked={pluginConfirmed}
            onChange={(event) => setPluginConfirmed(event.target.checked)}
          >
            {t("portabilityImport.pluginWarningConfirm")}
          </Checkbox>
        </Modal>
      </main>
    </div>
  );
}
