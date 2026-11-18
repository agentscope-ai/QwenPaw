import { useAutoSave } from "@/hooks/useAutoSave";
import { useState, useEffect, useCallback } from "react";
import { Button, Input, Popconfirm, Tag, Alert } from "@agentscope-ai/design";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { Space, Spin } from "antd";
import { Network, Plus, Trash2, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import styles from "../index.module.less";
import entries from "./SecurityEntries.module.less";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import NumberFlow from "@number-flow/react";

interface AllowNoAuthHostsTabProps {
  onSave?: (handlers: {
    save: () => Promise<void>;
    reset: () => void;
    saving: boolean;
  }) => void;
}

export function AllowNoAuthHostsTab({ onSave }: AllowNoAuthHostsTabProps = {}) {
  const { t } = useTranslation();
  const [hosts, setHosts] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const saving = false;
  const [loaded, setLoaded] = useState(false);
  const [inputError, setInputError] = useState("");
  const reduced = useReducedMotion();
  const [newHost, setNewHost] = useState("");
  const { message } = useAppMessage();
  const { schedule, flush } = useAutoSave(async () => {
    await api.updateAllowNoAuthHosts({ hosts });
  });

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getAllowNoAuthHosts();
      setHosts(data?.hosts ?? ["127.0.0.1", "::1"]);
      setLoaded(true);
    } catch {
      message.error(t("security.allowNoAuthHosts.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t, message]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const isValidIP = (ip: string): boolean => {
    // IPv4 validation
    const ipv4Regex =
      /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;

    // IPv6 validation - comprehensive regex supporting compressed notation
    // Matches: full format, compressed (::), leading/trailing compression
    const ipv6Regex =
      /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]+|::(ffff(:0{1,4})?:)?((25[0-5]|(2[0-4]|1?[0-9])?[0-9])\.){3}(25[0-5]|(2[0-4]|1?[0-9])?[0-9])|([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|(2[0-4]|1?[0-9])?[0-9])\.){3}(25[0-5]|(2[0-4]|1?[0-9])?[0-9]))$/;

    return ipv4Regex.test(ip) || ipv6Regex.test(ip);
  };

  const handleAdd = useCallback(() => {
    const trimmed = newHost.trim();
    if (!trimmed || !loaded) return;

    if (!isValidIP(trimmed)) {
      setInputError(t("security.allowNoAuthHosts.invalidIP"));
      return;
    }

    if (hosts.includes(trimmed)) {
      setInputError(t("security.allowNoAuthHosts.duplicate"));
      return;
    }

    setHosts((prev) => [...prev, trimmed]);
    schedule();
    setNewHost("");
    setInputError("");
  }, [newHost, hosts, t, loaded, schedule]);

  const handleRemove = useCallback(
    (host: string) => {
      setHosts((prev) => prev.filter((h) => h !== host));
      schedule();
    },
    [schedule],
  );

  const handleReset = useCallback(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    onSave?.({
      save: async () => {
        await flush();
      },
      reset: handleReset,
      saving,
    });
  }, [flush, handleReset, saving, onSave]);

  const isDefaultHost = (host: string) => {
    return host === "127.0.0.1" || host === "::1";
  };

  return (
    <div className={styles.tabContent}>
      <Alert
        message={t("security.allowNoAuthHosts.warningTitle")}
        description={t("security.allowNoAuthHosts.warningDescription")}
        type="warning"
        icon={<AlertTriangle size={16} />}
        showIcon
        style={{ marginBottom: 16 }}
      />

      <section
        className={entries.paths}
        aria-label={t("security.allowNoAuthHosts.ipAddress")}
      >
        <div className={entries.pathHeader}>
          <h3>
            {t("security.allowNoAuthHosts.ipAddress")}{" "}
            <NumberFlow value={hosts.length} respectMotionPreference />
          </h3>
          {!loaded && !loading && (
            <Button onClick={fetchData}>{t("common.retry")}</Button>
          )}
        </div>
        <Space.Compact className={entries.addInput}>
          <Input
            value={newHost}
            onChange={(e) => {
              setNewHost(e.target.value);
              setInputError("");
            }}
            placeholder={t("security.allowNoAuthHosts.inputPlaceholder")}
            aria-label={t("security.allowNoAuthHosts.ipAddress")}
            onPressEnter={handleAdd}
            allowClear
            disabled={!loaded || loading}
            status={inputError ? "error" : undefined}
            aria-invalid={!!inputError}
            aria-describedby={inputError ? "host-input-error" : undefined}
          />
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={handleAdd}
            disabled={!loaded || loading || !newHost.trim()}
          >
            {t("security.allowNoAuthHosts.add")}
          </Button>
        </Space.Compact>
        {inputError && (
          <p id="host-input-error" role="alert" className={entries.inputError}>
            {inputError}
          </p>
        )}
        <Spin spinning={loading}>
          <ul className={entries.pathList}>
            <AnimatePresence initial={false}>
              {hosts.map((host) => (
                <motion.li
                  key={host}
                  layout={!reduced}
                  className={entries.pathRow}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={
                    reduced
                      ? { duration: 0 }
                      : { type: "spring", stiffness: 360, damping: 38 }
                  }
                >
                  <Network size={17} aria-hidden="true" />
                  <code>{host}</code>
                  {isDefaultHost(host) && (
                    <Tag>{t("security.allowNoAuthHosts.default")}</Tag>
                  )}
                  <Popconfirm
                    title={t("security.allowNoAuthHosts.removeConfirm")}
                    description={<code>{host}</code>}
                    onConfirm={() => handleRemove(host)}
                    okText={t("common.delete")}
                    cancelText={t("common.cancel")}
                  >
                    <Button
                      type="text"
                      danger
                      icon={<Trash2 size={16} />}
                      aria-label={`${t("common.delete")}: ${host}`}
                    />
                  </Popconfirm>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
          {loaded && !hosts.length && (
            <p className={entries.empty}>
              {t("security.allowNoAuthHosts.empty")}
            </p>
          )}
        </Spin>
      </section>
    </div>
  );
}
