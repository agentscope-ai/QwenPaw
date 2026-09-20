import { useEffect, useState } from "react";
import { Empty, Input, Pagination, Spin } from "antd";
import { Plus, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { providerApi } from "../../../api/modules/provider";
import type { ModelPoolPage } from "../../../api/types";
import { useAppMessage } from "../../../hooks/useAppMessage";
import {
  BillingTag,
  CapabilityTags,
} from "../../Settings/Models/components/modals/ModelCapabilityTags";
import styles from "./index.module.less";

export default function ProviderCandidatePicker({
  providerId,
  tier,
  onSaved,
}: {
  providerId: string;
  tier: "pro" | "free";
  onSaved: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ModelPoolPage>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string>();
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      providerApi
        .getModelPool(providerId, {
          tab: "candidates",
          billing: tier,
          search,
          offset,
          limit: 10,
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
  }, [providerId, tier, search, offset, revision]);
  return (
    <section
      className={styles.candidatePicker}
      aria-label={t("modelSelector.addSelectorModel")}
    >
      <Input
        size="small"
        prefix={<Search size={14} />}
        aria-label={t("modelSelector.searchCandidates")}
        placeholder={t("modelSelector.searchCandidates")}
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
          setOffset(0);
        }}
        allowClear
      />
      <Spin spinning={loading} delay={150}>
        <div className={styles.candidateList} aria-busy={loading}>
          {page?.models.map((model) => (
            <div key={model.id} className={styles.candidateRow}>
              <span title={model.id}>{model.name || model.id}</span>
              <div className={styles.candidateTags}>
                <BillingTag model={model} iconOnly />
                <CapabilityTags model={model} iconOnly />
              </div>
              <button
                type="button"
                className={styles.addModelControl}
                disabled={loading || Boolean(busy)}
                aria-label={`${t("modelSelector.addToSelector")} ${
                  model.name || model.id
                }`}
                onClick={async () => {
                  setBusy(model.id);
                  try {
                    await providerApi.updateModelPool(providerId, model.id, {
                      selected: true,
                      seen: true,
                    });
                    setRevision((value) => value + 1);
                    await onSaved();
                  } catch (error) {
                    message.error(
                      error instanceof Error ? error.message : String(error),
                    );
                  } finally {
                    setBusy(undefined);
                  }
                }}
              >
                <Plus size={16} />
              </button>
            </div>
          ))}
          {!loading && !page?.models.length && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("modelSelector.noModelsFound")}
            />
          )}
        </div>
      </Spin>
      {(page?.total ?? 0) > 10 && (
        <Pagination
          size="small"
          simple
          current={Math.floor((page?.offset ?? 0) / 10) + 1}
          pageSize={10}
          total={page?.total}
          showSizeChanger={false}
          onChange={(value) => setOffset((value - 1) * 10)}
        />
      )}
    </section>
  );
}
