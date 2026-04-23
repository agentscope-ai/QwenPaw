import { useState, useEffect, useCallback } from "react";
import {
  Card,
  Button,
  Input,
  Table,
  Popconfirm,
  Tag,
  Alert,
} from "@agentscope-ai/design";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { Space } from "antd";
import { Shield, Plus, Trash2, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import styles from "../index.module.less";

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
  const [saving, setSaving] = useState(false);
  const [newHost, setNewHost] = useState("");
  const { message } = useAppMessage();

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getAllowNoAuthHosts();
      setHosts(data?.hosts ?? ["127.0.0.1", "::1"]);
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
    if (!trimmed) return;

    if (!isValidIP(trimmed)) {
      message.error(t("security.allowNoAuthHosts.invalidIP"));
      return;
    }

    if (hosts.includes(trimmed)) {
      message.warning(t("security.allowNoAuthHosts.duplicate"));
      return;
    }

    setHosts((prev) => [...prev, trimmed]);
    setNewHost("");
  }, [newHost, hosts, t, message]);

  const handleRemove = useCallback((host: string) => {
    setHosts((prev) => prev.filter((h) => h !== host));
  }, []);

  const handleSave = useCallback(async () => {
    try {
      setSaving(true);
      await api.updateAllowNoAuthHosts({ hosts });
      message.success(t("security.allowNoAuthHosts.saveSuccess"));
    } catch {
      message.error(t("security.allowNoAuthHosts.saveFailed"));
    } finally {
      setSaving(false);
    }
  }, [hosts, t, message]);

  const handleReset = useCallback(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    onSave?.({ save: handleSave, reset: handleReset, saving });
  }, [handleSave, handleReset, saving, onSave]);

  const isDefaultHost = (host: string) => {
    return host === "127.0.0.1" || host === "::1";
  };

  const columns = [
    {
      title: t("security.allowNoAuthHosts.ipAddress"),
      dataIndex: "host",
      key: "host",
      render: (host: string) => (
        <Space>
          <Shield size={16} style={{ color: "#52c41a" }} />
          <code style={{ fontSize: "13px" }}>{host}</code>
          {isDefaultHost(host) && (
            <Tag color="blue">{t("security.allowNoAuthHosts.default")}</Tag>
          )}
        </Space>
      ),
    },
    {
      title: t("security.allowNoAuthHosts.actions"),
      key: "actions",
      width: 80,
      render: (_: unknown, record: { host: string }) => (
        <Popconfirm
          title={t("security.allowNoAuthHosts.removeConfirm")}
          onConfirm={() => handleRemove(record.host)}
          okText={t("common.delete")}
          cancelText={t("common.cancel")}
        >
          <Button type="text" danger icon={<Trash2 size={16} />} size="small" />
        </Popconfirm>
      ),
    },
  ];

  const dataSource = hosts.map((host) => ({ key: host, host }));

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

      <Card className={styles.formCard}>
        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={newHost}
            onChange={(e) => setNewHost(e.target.value)}
            placeholder={t("security.allowNoAuthHosts.inputPlaceholder")}
            onPressEnter={handleAdd}
            allowClear
          />
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={handleAdd}
            disabled={!newHost.trim()}
          >
            {t("security.allowNoAuthHosts.add")}
          </Button>
        </Space.Compact>
      </Card>

      <Card className={styles.tableCard}>
        <Table
          columns={columns}
          dataSource={dataSource}
          loading={loading}
          pagination={false}
          size="middle"
          locale={{
            emptyText: t("security.allowNoAuthHosts.empty"),
          }}
        />
      </Card>
    </div>
  );
}
