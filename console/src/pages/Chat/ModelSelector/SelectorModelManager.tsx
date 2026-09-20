import { useEffect, useMemo, useState } from "react";
import { Button, Empty, Input, Pagination, Select, Spin, Tooltip } from "antd";
import { ArrowLeft, Plus, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  ModelInfo,
  ModelPoolPage,
  ProviderInfo,
} from "../../../api/types";
import { providerApi } from "../../../api/modules/provider";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { ProviderIcon } from "../../Settings/Models/components/ProviderIconComponent";
import { BillingTag } from "../../Settings/Models/components/modals/ModelCapabilityTags";
import styles from "./SelectorModelManager.module.less";

interface Props {
  providers: ProviderInfo[];
  activeProviderId?: string;
  activeModelId?: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
  onProviderUpdated: (provider: ProviderInfo) => void;
}

export default function SelectorModelManager({
  providers,
  activeProviderId,
  activeModelId,
  onClose,
  onSaved,
  onProviderUpdated,
}: Props) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [adding, setAdding] = useState(false);
  const [providerId, setProviderId] = useState<string>();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ModelPoolPage>();
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string>();
  const [revision, setRevision] = useState(0);
  const selected = useMemo(
    () =>
      providers.flatMap((provider) => {
        const models = new Map(
          [...provider.models, ...provider.extra_models].map((model) => [
            model.id,
            model,
          ]),
        );
        return [...models.values()].map((model) => ({ provider, model }));
      }),
    [providers],
  );
  const filtered = selected.filter(({ model, provider }) =>
    `${model.name} ${model.id} ${provider.name}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const provider = providers.find((item) => item.id === providerId);
  useEffect(() => {
    if (!adding || !providerId) return;
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      providerApi
        .getModelPool(providerId, {
          tab: "candidates",
          search,
          offset,
          limit: 30,
        })
        .then((result) => {
          if (!cancelled) setPage(result);
        })
        .catch((error) => {
          if (!cancelled) message.error(String(error));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [adding, providerId, search, offset, revision]);

  const changeSelection = async (
    owner: ProviderInfo,
    model: ModelInfo,
    selected: boolean,
  ) => {
    setBusy(`${owner.id}:${model.id}`);
    try {
      const updated = await providerApi.updateModelPool(owner.id, model.id, {
        selected,
        seen: true,
      });
      onProviderUpdated(updated);
      setRevision((value) => value + 1);
      await onSaved();
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(undefined);
    }
  };
  const changeStep = (value: boolean) => {
    setAdding(value);
    setSearch("");
    setOffset(0);
    setPage(undefined);
    setProviderId(undefined);
  };
  const selectedOffset = Math.min(
    offset,
    Math.max(0, Math.ceil(filtered.length / 30) - 1) * 30,
  );
  const rows = adding
    ? provider
      ? (page?.models ?? []).map((model) => ({ provider, model }))
      : []
    : filtered.slice(selectedOffset, selectedOffset + 30);
  const total = adding ? page?.total ?? 0 : filtered.length;
  return (
    <section
      className={styles.editor}
      aria-label={t("modelSelector.manageSelectorModels")}
    >
      <div className={styles.toolbar}>
        <strong>
          {t(
            adding
              ? "modelSelector.addSelectorModel"
              : "modelSelector.manageSelectorModels",
          )}
        </strong>
        <Button type="text" onClick={onClose}>
          {t("modelSelector.finishEditing")}
        </Button>
      </div>
      <div className={styles.toolbar}>
        {adding ? (
          <Button
            icon={<ArrowLeft size={15} />}
            onClick={() => changeStep(false)}
          >
            {t("modelSelector.backToSelected")}
          </Button>
        ) : (
          <span className={styles.count}>
            {t("modelSelector.selectedCount", { count: selected.length })}
          </span>
        )}
        {!adding && (
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={() => changeStep(true)}
          >
            {t("models.addModel")}
          </Button>
        )}
      </div>
      {adding && (
        <Select
          aria-label={t("models.provider")}
          placeholder={t("modelSelector.chooseProviderFirst")}
          value={providerId}
          showSearch
          optionFilterProp="label"
          className={styles.provider}
          getPopupContainer={(trigger) => trigger.parentElement!}
          options={providers
            .filter(
              (item) =>
                item.id !== "hub-managed" && item.id !== "qwenpaw-local",
            )
            .map((item) => ({ value: item.id, label: item.name }))}
          onChange={(id) => {
            setProviderId(id);
            setOffset(0);
            setPage(undefined);
          }}
        />
      )}
      {(!adding || providerId) && (
        <Input
          aria-label={t("modelSelector.searchModels")}
          placeholder={t("modelSelector.searchModels")}
          prefix={<Search size={15} />}
          allowClear
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setOffset(0);
          }}
        />
      )}
      <div className={styles.list} aria-busy={loading}>
        <Spin spinning={loading} delay={150}>
          {rows.map(({ provider: owner, model }) => {
            const key = `${owner.id}:${model.id}`;
            const active =
              owner.id === activeProviderId && model.id === activeModelId;
            const managed =
              owner.id === "hub-managed" || owner.id === "qwenpaw-local";
            return (
              <div className={styles.row} key={key}>
                <Tooltip title={owner.name}>
                  <span className={styles.logo}>
                    <ProviderIcon providerId={owner.id} size={24} />
                  </span>
                </Tooltip>
                <div className={styles.name}>
                  <strong title={model.name}>{model.name}</strong>
                  <span title={model.id}>{model.id}</span>
                </div>
                <BillingTag model={model} />
                <Tooltip
                  title={
                    !adding && (active || managed)
                      ? t(
                          active
                            ? "modelSelector.currentModelProtected"
                            : "modelSelector.managedModelProtected",
                        )
                      : undefined
                  }
                >
                  <Button
                    type="text"
                    icon={adding ? <Plus size={17} /> : <X size={17} />}
                    aria-label={`${t(
                      adding
                        ? "modelSelector.addToSelector"
                        : "modelSelector.removeFromSelector",
                    )} ${model.name}`}
                    disabled={Boolean(busy) || (!adding && (active || managed))}
                    loading={busy === key}
                    onClick={() => changeSelection(owner, model, adding)}
                  />
                </Tooltip>
              </div>
            );
          })}
          {!rows.length && !loading && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t(
                adding && !providerId
                  ? "modelSelector.chooseProviderFirst"
                  : "modelSelector.noModelsFound",
              )}
            />
          )}
        </Spin>
      </div>
      <div className={styles.pagination}>
        {total > 30 && (
          <Pagination
            size="small"
            current={
              Math.floor((adding ? page?.offset ?? 0 : selectedOffset) / 30) + 1
            }
            pageSize={30}
            total={total}
            showSizeChanger={false}
            onChange={(number) => setOffset((number - 1) * 30)}
          />
        )}
      </div>
    </section>
  );
}
