import { useMemo } from "react";
import { Button, Card, Modal, Table } from "@agentscope-ai/design";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import type { DataSourceRecord, DataSourceType } from "../../../api/types/dataSource";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { DATA_CONNECTION_TYPE_META } from "./types";
import { useDataConnections } from "./useDataConnections";
import styles from "./index.module.less";

function getDataConnectionRouteBase(): string {
  return window.location.pathname.startsWith("/plugin/datapaw/")
    ? "/plugin/datapaw/datapaw/data-connection"
    : "/datapaw/data-connection";
}

function navigateInHost(path: string): void {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function DataConnectionPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { connections, loading, removeConnection } = useDataConnections();
  const routeBase = getDataConnectionRouteBase();

  const handleDelete = (record: DataSourceRecord) => {
    Modal.confirm({
      title: t("dataConnection.confirmDeleteTitle"),
      content: t("dataConnection.confirmDelete", { name: record.name }),
      okText: t("common.delete"),
      okType: "primary",
      cancelText: t("common.cancel"),
      onOk: async () => {
        try {
          await removeConnection(record.id);
          message.success(t("dataConnection.deleteSuccess"));
        } catch (error) {
          console.error("Failed to delete data source:", error);
          message.error(t("dataConnection.deleteFailed"));
        }
      },
    });
  };

  const columns: ColumnsType<DataSourceRecord> = useMemo(
    () => [
      {
        title: t("dataConnection.type"),
        dataIndex: "type",
        key: "type",
        width: 220,
        render: (type: DataSourceType) => {
          const meta = DATA_CONNECTION_TYPE_META[type];
          return (
            <div className={styles.typeCell}>
              <span
                className={styles.typeBadge}
                style={{ backgroundColor: meta.accent }}
              >
                {meta.badge}
              </span>
              <span className={styles.typeLabel}>{t(meta.labelKey)}</span>
            </div>
          );
        },
      },
      {
        title: t("dataConnection.name"),
        dataIndex: "name",
        key: "name",
      },
      {
        title: t("common.actions"),
        key: "actions",
        width: 120,
        render: (_, record) => (
          <Button
            type="link"
            danger
            className={styles.deleteAction}
            onClick={() => handleDelete(record)}
          >
            {t("common.delete")}
          </Button>
        ),
      },
    ],
    [t],
  );

  return (
    <div className={styles.dataConnectionPage}>
      <PageHeader
        items={[
          { title: t("dataConnection.title") },
        ]}
        subRow={
          <p className={styles.description}>{t("dataConnection.description")}</p>
        }
      />

      <Card className={styles.tableCard} bodyStyle={{ padding: 0 }} extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigateInHost(`${routeBase}/add`)}
        >
          {t("dataConnection.add")}
        </Button>
      }>
        <Table
          columns={columns}
          dataSource={connections}
          loading={loading}
          rowKey="id"
          pagination={{
            pageSize: 10,
            showTotal: (total) => t("common.total", { count: total }),
          }}
        />
      </Card>
    </div>
  );
}

export default DataConnectionPage;
