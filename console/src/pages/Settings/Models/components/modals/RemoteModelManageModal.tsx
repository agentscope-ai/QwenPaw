import { useState, useEffect, useMemo, useDeferredValue, useRef } from "react";
import { Button, Form, Modal, Tag, Tooltip } from "@agentscope-ai/design";
import { Pagination, Select, Spin, Switch } from "antd";
import {
  ChevronDown,
  FlaskConical,
  PlugZap,
  Plus,
  RefreshCw,
  Settings,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  ModelInfo,
  ProviderInfo,
  ModelPoolPage,
} from "../../../../../api/types";
import api from "../../../../../api";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import { ModelIdentityFields } from "./ModelIdentityFields";
import { ModelInfoPreview } from "./ModelInfoPreview";
import { ModelConfigEditor } from "./ModelConfigEditor";
import { BillingTag, CapabilityTags } from "./ModelCapabilityTags";
import { ModelPoolFilters } from "./ModelPoolFilters";
import { emptyPoolFilters } from "./modelPool";
import { getLocalizedTestConnectionMessage } from "./testConnectionMessage";
import styles from "./ModelPool.module.less";

interface RemoteModelManageModalProps {
  provider: ProviderInfo;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
  onProviderUpdated?: (provider: ProviderInfo) => void;
}

export function RemoteModelManageModal({
  provider,
  open,
  onClose,
  onSaved,
  onProviderUpdated,
}: RemoteModelManageModalProps) {
  const { t, i18n } = useTranslation();
  const { message } = useAppMessage();
  const [current, setCurrent] = useState(provider);
  const [tab, setTab] = useState("all");
  const [filters, setFilters] = useState(emptyPoolFilters);
  const deferredFilters = useDeferredValue(filters);
  const [page, setPage] = useState<ModelPoolPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [configId, setConfigId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [templateId, setTemplateId] = useState<string>();
  const [form] = Form.useForm();
  const enteredModelId = Form.useWatch("id", form);
  const seen = useRef(new Set(provider.seen_model_ids ?? []));
  const [seenIds, setSeenIds] = useState(seen.current);
  const hoverTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const managed = provider.id === "hub-managed";

  useEffect(() => {
    setCurrent(provider);
    seen.current = new Set([
      ...seen.current,
      ...(provider.seen_model_ids ?? []),
    ]);
    setSeenIds(new Set(seen.current));
  }, [provider]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .getModelPool(provider.id, {
          ...deferredFilters,
          tab: managed ? "selected" : tab,
          offset,
          limit: 30,
        })
        .then((result) => {
          if (active) setPage(result);
        })
        .catch((error) => {
          if (active)
            message.error(
              error instanceof Error
                ? error.message
                : t("models.autoDiscoverModelsFailed"),
            );
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 150);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [open, provider, deferredFilters, tab, offset, revision]);
  useEffect(() => {
    const timers = hoverTimers.current;
    return () => timers.forEach(clearTimeout);
  }, []);

  const selectedIds = useMemo(
    () =>
      new Set(
        [...(current.models ?? []), ...(current.extra_models ?? [])].map(
          (model) => model.id,
        ),
      ),
    [current.models, current.extra_models],
  );
  const rows = page?.models ?? [];
  const families = page?.families ?? [];
  const refresh = () => setRevision((value) => value + 1);

  const apply = async (updated: ProviderInfo) => {
    setCurrent(updated);
    refresh();
    onProviderUpdated?.(updated);
    await onSaved();
  };
  const failure = (error: unknown) =>
    message.error(
      error instanceof Error
        ? error.message
        : t("models.modelConfigSaveFailed"),
    );
  const markSeen = (id: string) => {
    if (seen.current.has(id) || managed || loading) return;
    seen.current.add(id);
    setSeenIds(new Set(seen.current));
    void api.updateModelPool(provider.id, id, { seen: true }).catch(() => {
      seen.current.delete(id);
      setSeenIds(new Set(seen.current));
    });
  };
  const startHover = (id: string) => {
    if (!hoverTimers.current.has(id))
      hoverTimers.current.set(
        id,
        setTimeout(() => {
          hoverTimers.current.delete(id);
          markSeen(id);
        }, 600),
      );
  };
  const endHover = (id: string) => {
    clearTimeout(hoverTimers.current.get(id));
    hoverTimers.current.delete(id);
  };
  const select = async (model: ModelInfo, selected: boolean) => {
    setBusy(model.id);
    try {
      await apply(
        await api.updateModelPool(provider.id, model.id, {
          selected,
          seen: true,
        }),
      );
      seen.current.add(model.id);
      setSeenIds(new Set(seen.current));
    } catch (error) {
      failure(error);
    } finally {
      setBusy(null);
    }
  };
  const discover = async () => {
    setSyncing(true);
    try {
      const result = await api.discoverModels(provider.id, undefined, true);
      if (result.success) {
        setCurrent((value) => ({
          ...value,
          models_last_sync_error: null,
          models_last_synced_at: result.last_synced_at,
        }));
        setOffset(0);
        refresh();
        await onSaved();
        setTab("all");
        message.success(
          t("models.pool.discovered", { count: result.discovered_count }),
        );
      } else
        message.error(
          result.error_kind === "unsupported"
            ? t("models.pool.unsupported")
            : result.message || t("models.autoDiscoverModelsFailed"),
        );
    } catch (error) {
      failure(error);
    } finally {
      setSyncing(false);
    }
  };
  const test = async (model: ModelInfo, probe = false) => {
    setBusy(model.id);
    try {
      if (probe) {
        const result = await api.probeMultimodal(provider.id, model.id);
        message.info(
          result.supports_image === true
            ? t("models.probeImage")
            : t("models.pool.probeFinished"),
        );
      } else {
        const result = await api.testModelConnection(provider.id, {
          model_id: model.id,
        });
        message[result.success ? "success" : "warning"](
          getLocalizedTestConnectionMessage(result, t),
        );
      }
      refresh();
      await onSaved();
    } catch (error) {
      failure(error);
    } finally {
      setBusy(null);
    }
  };
  const addManual = async () => {
    try {
      const values = await form.validateFields();
      setBusy("manual");
      const id = values.id.trim();
      if (selectedIds.has(id)) {
        message.warning(t("models.modelAlreadyExists", { id }));
        return;
      }
      await api.addModel(provider.id, {
        id,
        name: values.name?.trim() || id,
        template_id: templateId,
      });
      await onSaved();
      refresh();
      setAdding(false);
      setTab("all");
      form.resetFields();
      setTemplateId(undefined);
    } catch (error) {
      if (!(error && typeof error === "object" && "errorFields" in error))
        failure(error);
    } finally {
      setBusy(null);
    }
  };
  const number = (value?: number | null) =>
    value == null ? t("models.unknown") : value.toLocaleString(i18n.language);

  return (
    <Modal
      title={t("models.manageModelsTitle", { provider: current.name })}
      open={open}
      onCancel={onClose}
      footer={null}
      width={860}
      centered
      destroyOnHidden
      className={styles.modal}
    >
      <div className={styles.toolbar}>
        <Select
          aria-label={t("models.pool.selectionFilter")}
          value={managed ? "selected" : tab}
          onChange={(value) => {
            setTab(value);
            setOffset(0);
            setConfigId(null);
          }}
          options={[
            ...(!managed
              ? [
                  {
                    value: "all",
                    label: t("models.pool.all", {
                      count:
                        (page?.candidate_count ?? 0) +
                        (page?.selected_count ?? selectedIds.size),
                    }),
                  },
                ]
              : []),
            {
              value: "selected",
              label: t("models.pool.selected", {
                count: page?.selected_count ?? selectedIds.size,
              }),
            },
            ...(!managed
              ? [
                  {
                    value: "candidates",
                    label: t("models.pool.candidates", {
                      count: page?.candidate_count ?? 0,
                    }),
                  },
                ]
              : []),
          ]}
        />
        {!managed && current.support_model_discovery && (
          <Button
            icon={<RefreshCw size={16} />}
            loading={syncing || current.models_syncing}
            onClick={discover}
          >
            {t("models.autoDiscoverModels")}
          </Button>
        )}
      </div>
      <p className={styles.hint}>
        {t(managed ? "models.pool.managedHint" : "models.pool.hint")}
      </p>
      {!current.support_model_discovery && current.discovery_support_reason && (
        <p className={styles.hint}>{current.discovery_support_reason}</p>
      )}
      <ModelPoolFilters
        value={filters}
        onChange={(value) => {
          setFilters(value);
          setOffset(0);
          setConfigId(null);
        }}
        families={families}
      />
      <div className={styles.summary}>
        <span>{t("models.pool.results", { count: page?.total ?? 0 })}</span>
        <span>
          {current.models_last_synced_at &&
            t("models.modelsLastSynced", {
              time: new Date(current.models_last_synced_at).toLocaleString(),
            })}
        </span>
      </div>
      {current.models_last_sync_error && (
        <div role="alert" className={styles.error}>
          {current.models_last_sync_error}
        </div>
      )}
      <div className={styles.list} aria-busy={loading}>
        <Spin spinning={loading} delay={150}>
          {loading && !page && (
            <div role="status" className={styles.empty}>
              {t("common.loading")}
            </div>
          )}
          {!loading && rows.length === 0 && (
            <div className={styles.empty}>
              <strong>{t("models.pool.empty")}</strong>
              <span>{t("models.pool.emptyHint")}</span>
            </div>
          )}
          {rows.map((model) => {
            const isSelected = selectedIds.has(model.id);
            const isNew = !isSelected && !seenIds.has(model.id);
            const expanded = configId === model.id;
            return (
              <div
                key={model.id}
                className={styles.entry}
                data-model-id={model.id}
                onMouseEnter={() => startHover(model.id)}
                onMouseLeave={() => endHover(model.id)}
                onFocus={() => markSeen(model.id)}
                onClick={() => markSeen(model.id)}
              >
                <div className={styles.row}>
                  <div className={styles.identity}>
                    <div className={styles.name}>
                      <strong>{model.name}</strong>
                      {isNew && <span className={styles.newBadge}>New</span>}
                    </div>
                    <span className={styles.id} title={model.id}>
                      {model.id}
                    </span>
                    <div className={styles.facts}>
                      <CapabilityTags model={model} />
                      {model.remote_missing && (
                        <Tag color="warning">{t("models.remoteMissing")}</Tag>
                      )}
                      <BillingTag model={model} />
                      <span>
                        {t("models.pool.context")}:{" "}
                        {number(
                          model.effective_max_input_length ??
                            model.max_input_length,
                        )}
                      </span>
                      <span>
                        {t("models.pool.output")}:{" "}
                        {number(model.max_output_length)}
                      </span>
                    </div>
                  </div>
                  <div className={styles.actions}>
                    {!managed && (
                      <>
                        {model.requires_paid_confirmation && isSelected && (
                          <Button
                            onClick={async () => {
                              try {
                                await apply(
                                  await api.configureModel(
                                    provider.id,
                                    model.id,
                                    { confirm_paid: true },
                                  ),
                                );
                              } catch (error) {
                                failure(error);
                              }
                            }}
                          >
                            {t("models.enablePaidModel")}
                          </Button>
                        )}
                        <Tooltip title={t("models.testConnection")}>
                          <Button
                            type="text"
                            icon={<PlugZap size={17} />}
                            aria-label={t("models.testConnection")}
                            disabled={loading || busy !== null}
                            onClick={() => test(model)}
                          />
                        </Tooltip>
                        <Tooltip title={t("models.modelConfigLabel")}>
                          <Button
                            disabled={loading}
                            type="text"
                            icon={
                              expanded ? (
                                <ChevronDown size={17} />
                              ) : (
                                <Settings size={17} />
                              )
                            }
                            aria-label={t("models.modelConfigLabel")}
                            onClick={() =>
                              setConfigId(expanded ? null : model.id)
                            }
                          />
                        </Tooltip>
                        <label className={styles.selectionToggle}>
                          <span>
                            {t(
                              isSelected
                                ? "models.pool.enabled"
                                : "models.pool.disabled",
                            )}
                          </span>
                          <Switch
                            checked={isSelected}
                            aria-label={`${t("models.pool.selectorToggle")} ${
                              model.name
                            }`}
                            loading={busy === model.id}
                            disabled={
                              loading ||
                              syncing ||
                              current.models_syncing ||
                              (busy !== null && busy !== model.id)
                            }
                            onChange={(checked) => select(model, checked)}
                          />
                        </label>
                      </>
                    )}
                  </div>
                </div>
                {expanded && (
                  <div className={styles.details}>
                    <>
                      <ModelConfigEditor
                        providerId={current.id}
                        model={model}
                        onSaved={onSaved}
                        onProviderUpdated={(updated) => {
                          setCurrent(updated);
                          refresh();
                          onProviderUpdated?.(updated);
                        }}
                        onClose={() => setConfigId(null)}
                        chatModel={current.chat_model}
                        thinkingParamStyle={
                          model.thinking_param_style ??
                          current.thinking_param_style
                        }
                        reasoningEffortOptions={
                          model.reasoning_effort_options ??
                          current.reasoning_effort_options
                        }
                        thinkingBudgetRange={
                          (model.thinking_budget_range ??
                            current.thinking_budget_range) as
                            | [number, number]
                            | undefined
                        }
                      />
                      <Button
                        type="text"
                        icon={<FlaskConical size={16} />}
                        disabled={loading || busy !== null}
                        onClick={() => test(model, true)}
                      >
                        {t("models.probeMultimodal")}
                      </Button>
                    </>
                  </div>
                )}
              </div>
            );
          })}
        </Spin>
      </div>
      <div className={styles.pagination}>
        {(page?.total ?? 0) > 30 && (
          <Pagination
            size="small"
            current={Math.floor((page?.offset ?? offset) / 30) + 1}
            pageSize={30}
            total={page?.total ?? 0}
            showSizeChanger={false}
            disabled={loading}
            onChange={(number) => {
              setOffset((number - 1) * 30);
              setConfigId(null);
            }}
          />
        )}
      </div>
      {!managed && (
        <div className={styles.footer}>
          <span>{t("models.pool.manualHint")}</span>
          <Button icon={<Plus size={16} />} onClick={() => setAdding(true)}>
            {t("models.addModel")}
          </Button>
        </div>
      )}
      <Modal
        title={t("models.addModel")}
        open={adding}
        onCancel={() => setAdding(false)}
        onOk={addManual}
        confirmLoading={busy === "manual"}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <ModelIdentityFields
            options={rows
              .filter((model) => !selectedIds.has(model.id))
              .map((model) => ({ value: model.id, label: model.name }))}
            loading={false}
          />
          <ModelInfoPreview
            providerId={current.id}
            modelId={enteredModelId}
            templateId={templateId}
            onTemplateChange={setTemplateId}
          />
        </Form>
      </Modal>
    </Modal>
  );
}
