import { useEffect, useState, useSyncExternalStore } from "react";
import { Form, Input } from "antd";
import { Blocks, Check, PawPrint, SquareTerminal } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  HarnessSettings,
  harnessRegistry,
  refreshHarnessCatalog,
} from "@/plugins/harnesses";
import styles from "./AgentBackendFields.module.less";

interface AgentBackendFieldsProps {
  form: ReturnType<typeof Form.useForm>[0];
  open: boolean;
}

function StoredSettings() {
  return null;
}

export function AgentBackendFields({ form, open }: AgentBackendFieldsProps) {
  const { t } = useTranslation();
  const backend =
    (Form.useWatch("backend", form) as string | undefined) ?? "qwenpaw";
  const settings =
    Form.useWatch("backend_settings", form) ??
    form.getFieldValue("backend_settings") ??
    {};
  const [showPlugins, setShowPlugins] = useState(false);
  const rows = useSyncExternalStore(
    harnessRegistry.subscribe,
    harnessRegistry.getSnapshot,
    harnessRegistry.getSnapshot,
  );
  useEffect(() => {
    if (open) void refreshHarnessCatalog().catch(() => {});
  }, [open]);
  const selected = rows.find((row) => row.id === backend);
  const select = (id: string) => {
    if (id !== backend)
      form.setFieldsValue({ backend: id, backend_settings: {} });
  };
  return (
    <section className={styles.section}>
      <Form.Item name="backend" hidden>
        <Input />
      </Form.Item>
      <Form.Item name="backend_settings" hidden>
        <StoredSettings />
      </Form.Item>
      <div className={styles.sectionHeading}>
        <span className={styles.eyebrow}>{t("agent.backend.eyebrow")}</span>
        <h3>{t("agent.backend.typeTitle")}</h3>
        <p>{t("agent.backend.typeDescription")}</p>
      </div>
      <div className={styles.typeGrid}>
        <button
          type="button"
          className={`${styles.typeCard} ${
            backend === "qwenpaw" ? styles.selected : ""
          }`}
          aria-pressed={backend === "qwenpaw"}
          onClick={() => select("qwenpaw")}
        >
          <span className={styles.typeIcon}>
            <PawPrint size={20} />
          </span>
          <span className={styles.typeCopy}>
            <strong>{t("agent.backend.nativeTitle")}</strong>
            <small>{t("agent.backend.nativeDescription")}</small>
          </span>
          <span className={styles.radioMark} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={`${styles.typeCard} ${
            backend !== "qwenpaw" ? styles.selected : ""
          }`}
          aria-pressed={backend !== "qwenpaw"}
          onClick={() => setShowPlugins(true)}
        >
          <span className={styles.typeIcon}>
            <Blocks size={20} />
          </span>
          <span className={styles.typeCopy}>
            <strong>{t("agent.backend.thirdPartyTitle")}</strong>
            <small>{t("agent.backend.thirdPartyDescription")}</small>
          </span>
          <span className={styles.radioMark} aria-hidden="true" />
        </button>
      </div>
      {(showPlugins || backend !== "qwenpaw") && (
        <div className={styles.thirdPartyPanel}>
          <div className={styles.panelHeading}>
            <h4>{t("agent.backend.providerTitle")}</h4>
            <p>{t("agent.backend.providerDescription")}</p>
          </div>
          <div className={styles.providerGrid}>
            {rows
              .filter((row) => row.id !== "qwenpaw")
              .map((row) => (
                <button
                  type="button"
                  key={row.id}
                  disabled={row.status !== "available"}
                  aria-pressed={backend === row.id}
                  className={
                    row.status !== "available"
                      ? styles.providerCardDisabled
                      : backend === row.id
                      ? styles.providerCardSelected
                      : styles.providerCard
                  }
                  onClick={() => select(row.id)}
                >
                  <span className={styles.providerIcon}>
                    <SquareTerminal size={18} />
                  </span>
                  <span className={styles.providerCopy}>
                    <strong>{row.label}</strong>
                    {row.status !== "available" && (
                      <small>{t(`agent.backend.states.${row.status}`)}</small>
                    )}
                  </span>
                  {backend === row.id && (
                    <Check
                      size={15}
                      className={styles.providerCheck}
                      aria-hidden="true"
                    />
                  )}
                </button>
              ))}
          </div>
          <a href="/market?tab=plugins&view=official">
            {t("agent.backend.installPlugin")}
          </a>
          {backend !== "qwenpaw" && selected?.status !== "available" && (
            <p role="status">
              {backend} ·{" "}
              {t(`agent.backend.states.${selected?.status ?? "missing"}`)}
            </p>
          )}
          {backend !== "qwenpaw" && (
            <HarnessSettings
              backendId={backend}
              value={settings}
              open={open}
              onChange={(value) =>
                form.setFieldValue("backend_settings", value)
              }
            />
          )}
        </div>
      )}
    </section>
  );
}
