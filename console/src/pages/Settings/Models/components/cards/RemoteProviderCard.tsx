import { useLayoutEffect, useRef, useState } from "react";
import { Card, Button, Tag, Modal, message } from "@agentscope-ai/design";
import {
  EditOutlined,
  DeleteOutlined,
  AppstoreOutlined,
} from "@ant-design/icons";
import type { ProviderInfo, ActiveModelsInfo } from "../../../../../api/types";
import { ProviderConfigModal } from "../modals/ProviderConfigModal";
import { ModelManageModal } from "../modals/ModelManageModal";
import api from "../../../../../api";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

interface RemoteProviderCardProps {
  provider: ProviderInfo;
  activeModels: ActiveModelsInfo | null;
  onSaved: () => void;
  isHover: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function RemoteProviderCard({
  provider,
  activeModels,
  onSaved,
  isHover,
  onMouseEnter,
  onMouseLeave,
}: RemoteProviderCardProps) {
  const { t } = useTranslation();
  const [modalOpen, setModalOpen] = useState(false);
  const [modelManageOpen, setModelManageOpen] = useState(false);
  const titleRef = useRef<HTMLSpanElement | null>(null);
  const [isTitleWrapped, setIsTitleWrapped] = useState(false);

  useLayoutEffect(() => {
    const titleElement = titleRef.current;
    if (!titleElement) {
      return;
    }

    const checkWrapped = () => {
      const computedStyle = window.getComputedStyle(titleElement);
      const lineHeight = Number.parseFloat(computedStyle.lineHeight || "0");
      if (!lineHeight) {
        setIsTitleWrapped(false);
        return;
      }
      const titleHeight = titleElement.getBoundingClientRect().height;
      setIsTitleWrapped(titleHeight > lineHeight * 1.4);
    };

    checkWrapped();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const resizeObserver = new ResizeObserver(checkWrapped);
    resizeObserver.observe(titleElement);
    return () => {
      resizeObserver.disconnect();
    };
  }, [provider.name]);

  const handleDeleteProvider = (e: React.MouseEvent) => {
    e.stopPropagation();
    Modal.confirm({
      title: t("models.deleteProvider"),
      content: t("models.deleteProviderConfirm", { name: provider.name }),
      okText: t("common.delete"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        try {
          await api.deleteCustomProvider(provider.id);
          message.success(t("models.providerDeleted", { name: provider.name }));
          onSaved();
        } catch (error) {
          const errMsg =
            error instanceof Error
              ? error.message
              : t("models.providerDeleteFailed");
          message.error(errMsg);
        }
      },
    });
  };

  const totalCount = provider.models.length + provider.extra_models.length;

  let isConfigured = false;

  if (provider.is_local) {
    isConfigured = true;
  } else if (provider.is_custom && provider.base_url) {
    isConfigured = true;
  } else if (provider.require_api_key === false) {
    isConfigured = true;
  } else if (provider.require_api_key && provider.api_key) {
    isConfigured = true;
  }

  const hasModels = totalCount > 0;
  const isAvailable = isConfigured && hasModels;

  const providerTag = provider.is_custom ? (
    <Tag color="blue" style={{ fontSize: 11 }}>
      {t("models.custom")}
    </Tag>
  ) : (
    <Tag color="green" style={{ fontSize: 11 }}>
      {t("models.builtin")}
    </Tag>
  );

  const statusLabel = isAvailable
    ? t("models.providerAvailable")
    : isConfigured
    ? t("models.providerNoModels")
    : t("models.providerNotConfigured");
  const statusType = isAvailable
    ? "enabled"
    : isConfigured
    ? "partial"
    : "disabled";
  const statusDotColor = isAvailable
    ? "#52c41a"
    : isConfigured
    ? "#faad14"
    : "#d9d9d9";
  const statusDotShadow = isAvailable
    ? "0 0 0 2px rgba(82, 196, 26, 0.2)"
    : isConfigured
    ? "0 0 0 2px rgba(250, 173, 20, 0.2)"
    : "none";

  const titleWords = provider.name.trim().split(/\s+/).filter(Boolean);
  const wrappedTitleLine1 =
    titleWords.length > 1 ? titleWords.slice(0, -1).join(" ") : provider.name;
  const wrappedTitleLine2 =
    titleWords.length > 1 ? titleWords[titleWords.length - 1] : "";
  const shouldUseWrappedTitleLayout = isTitleWrapped && titleWords.length > 1;

  const statusLabelMatch = statusLabel.match(/^(.+?)\s*([（(])(.+)([）)])\s*$/);
  const statusMainText = statusLabelMatch?.[1]?.trim() ?? statusLabel;
  const statusMetaOpen = statusLabelMatch?.[2] ?? "";
  const statusMetaText = statusLabelMatch?.[3]?.trim();
  const statusMetaClose = statusLabelMatch?.[4] ?? "";

  return (
    <Card
      hoverable
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={`${styles.providerCard} ${
        isAvailable ? styles.enabledCard : ""
      } ${isHover ? styles.hover : styles.normal}`}
    >
      <div style={{ marginBottom: 16, paddingTop: 4 }}>
        <div className={styles.cardHeader}>
          <div
            className={`${styles.cardName} ${
              shouldUseWrappedTitleLayout ? styles.cardNameWrapped : ""
            }`}
          >
            <span ref={titleRef} className={styles.cardNameMeasure}>
              {provider.name}
            </span>
            {shouldUseWrappedTitleLayout ? (
              <>
                <span className={styles.cardNameLine1} title={provider.name}>
                  {wrappedTitleLine1}
                </span>
                <span className={styles.cardNameLine2Wrap}>
                  <span className={styles.cardNameLine2} title={provider.name}>
                    {wrappedTitleLine2}
                  </span>
                  <span className={styles.cardTagRow}>{providerTag}</span>
                </span>
              </>
            ) : (
              <>
                <span className={styles.cardNameText}>{provider.name}</span>
                <span className={styles.cardTagRow}>{providerTag}</span>
              </>
            )}
          </div>
          <div className={styles.statusContainer}>
            <span
              className={`${styles.statusText} ${
                statusType === "enabled"
                  ? styles.enabled
                  : statusType === "partial"
                  ? styles.partial
                  : styles.disabled
              }`}
            >
              <span className={styles.statusMainRow}>
                <span className={styles.statusTextMain}>{statusMainText}</span>
                <span
                  className={styles.statusDot}
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    backgroundColor: statusDotColor,
                    boxShadow: statusDotShadow,
                  }}
                />
              </span>
              <span className={styles.statusTextMeta}>
                {statusMetaText
                  ? `${statusMetaOpen}${statusMetaText}${statusMetaClose}`
                  : "\u00A0"}
              </span>
            </span>
          </div>
        </div>

        <div className={styles.cardInfo}>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>{t("models.baseURL")}:</span>
            {provider.base_url ? (
              <span className={styles.infoValue} title={provider.base_url}>
                {provider.base_url}
              </span>
            ) : (
              <span className={styles.infoEmpty}>{t("models.notSet")}</span>
            )}
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>{t("models.apiKey")}:</span>
            {provider.api_key ? (
              <span className={styles.infoValue}>{provider.api_key}</span>
            ) : (
              <span className={styles.infoEmpty}>{t("models.notSet")}</span>
            )}
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>{t("models.model")}:</span>
            <span className={styles.infoValue}>
              {totalCount > 0
                ? t("models.modelsCount", { count: totalCount })
                : t("models.noModels")}
            </span>
          </div>
        </div>
      </div>

      <div className={styles.cardActions}>
        <Button
          type="link"
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            setModelManageOpen(true);
          }}
          className={`${styles.configBtn} ${styles.configBtnNeutral}`}
          icon={<AppstoreOutlined />}
        >
          {t("models.manageModels")}
        </Button>
        <Button
          type="link"
          size="small"
          onClick={(e) => {
            e.stopPropagation();
            setModalOpen(true);
          }}
          className={`${styles.configBtn} ${styles.configBtnNeutral}`}
          icon={<EditOutlined />}
        >
          {t("models.settings")}
        </Button>
        {provider.is_custom && (
          <Button
            type="link"
            size="small"
            danger
            onClick={handleDeleteProvider}
            className={styles.configBtn}
            icon={<DeleteOutlined />}
          >
            <span className={styles.deleteTextLong}>
              {t("models.deleteProvider")}
            </span>
            <span className={styles.deleteTextShort}>{t("common.delete")}</span>
          </Button>
        )}
      </div>

      <ProviderConfigModal
        provider={provider}
        activeModels={activeModels}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={onSaved}
      />
      <ModelManageModal
        provider={provider}
        open={modelManageOpen}
        onClose={() => setModelManageOpen(false)}
        onSaved={onSaved}
      />
    </Card>
  );
}
