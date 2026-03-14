import { useLayoutEffect, useRef, useState } from "react";
import { Card, Button, Tag } from "@agentscope-ai/design";
import { AppstoreOutlined } from "@ant-design/icons";
import type { ProviderInfo } from "../../../../../api/types";
import { ModelManageModal } from "../modals/ModelManageModal";
import { useTranslation } from "react-i18next";
import styles from "../../index.module.less";

interface LocalProviderCardProps {
  provider: ProviderInfo;
  onSaved: () => void;
  isHover: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function LocalProviderCard({
  provider,
  onSaved,
  isHover,
  onMouseEnter,
  onMouseLeave,
}: LocalProviderCardProps) {
  const { t } = useTranslation();
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
    const resizeObserver = new ResizeObserver(checkWrapped);
    resizeObserver.observe(titleElement);
    return () => {
      resizeObserver.disconnect();
    };
  }, [provider.name]);

  const totalCount = provider.models.length + provider.extra_models.length;
  const statusReady = totalCount > 0;
  const statusLabel = statusReady
    ? t("models.available")
    : t("models.unavailable");
  const titleWords = provider.name.trim().split(/\s+/).filter(Boolean);
  const wrappedTitleLine1 =
    titleWords.length > 1 ? titleWords.slice(0, -1).join(" ") : provider.name;
  const wrappedTitleLine2 =
    titleWords.length > 1 ? titleWords[titleWords.length - 1] : provider.name;

  return (
    <Card
      hoverable
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={`${styles.providerCard} ${
        statusReady ? styles.enabledCard : ""
      } ${isHover ? styles.hover : styles.normal}`}
    >
      <div style={{ marginBottom: 16, paddingTop: 4 }}>
        <div className={styles.cardHeader}>
          <div
            className={`${styles.cardName} ${
              isTitleWrapped ? styles.cardNameWrapped : ""
            }`}
          >
            <span ref={titleRef} className={styles.cardNameMeasure}>
              {provider.name}
            </span>
            {isTitleWrapped ? (
              <>
                <span className={styles.cardNameLine1} title={provider.name}>
                  {wrappedTitleLine1}
                </span>
                <span className={styles.cardNameLine2Wrap}>
                  <span className={styles.cardNameLine2} title={provider.name}>
                    {wrappedTitleLine2}
                  </span>
                  <span className={styles.cardTagRow}>
                    <Tag color="purple" style={{ fontSize: 11 }}>
                      {t("models.local")}
                    </Tag>
                  </span>
                </span>
              </>
            ) : (
              <>
                <span className={styles.cardNameText}>
                  {provider.name}
                </span>
                <span className={styles.cardTagRow}>
                  <Tag color="purple" style={{ fontSize: 11 }}>
                    {t("models.local")}
                  </Tag>
                </span>
              </>
            )}
          </div>
          <div className={styles.statusContainer}>
            <span
              className={`${styles.statusText} ${
                statusReady ? styles.enabled : styles.disabled
              }`}
            >
              <span className={styles.statusMainRow}>
                <span className={styles.statusTextMain}>{statusLabel}</span>
                <span
                  className={styles.statusDot}
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    backgroundColor: statusReady ? "#52c41a" : "#d9d9d9",
                    boxShadow: statusReady
                      ? "0 0 0 2px rgba(82, 196, 26, 0.2)"
                      : "none",
                  }}
                />
              </span>
              <span className={styles.statusTextMeta}>{"\u00A0"}</span>
            </span>
          </div>
        </div>

        <div className={styles.cardInfo}>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>{t("models.localType")}:</span>
            <span className={styles.infoValue}>
              {t("models.localEmbedded")}
            </span>
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>{t("models.model")}:</span>
            <span className={styles.infoValue}>
              {totalCount > 0
                ? t("models.modelsCount", { count: totalCount })
                : t("models.localDownloadFirst")}
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
          className={styles.configBtn}
          icon={<AppstoreOutlined />}
        >
          {t("models.manageModels")}
        </Button>
      </div>

      <ModelManageModal
        provider={provider}
        open={modelManageOpen}
        onClose={() => setModelManageOpen(false)}
        onSaved={onSaved}
      />
    </Card>
  );
}
