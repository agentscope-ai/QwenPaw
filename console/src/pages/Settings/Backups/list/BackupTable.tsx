/**
 * Renders the paginated backup list with inline Restore / Export / Delete actions.
 * Accepts the full backup list and a searchQuery; filtering is done in-component
 * via useMemo so the parent doesn't need to maintain a filtered copy.
 *
 * Export shows a danger-confirmation modal before downloading the zip.
 * Delete calls the API directly and triggers onRefresh on success.
 * Restore delegates to the parent via onRestore (handled by useRestoreFlow).
 */
import { useMemo } from "react";
import { Button, Card, Empty, Modal, Popconfirm, Table, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import api from "@/api";
import { useAppMessage } from "@/hooks/useAppMessage";
import type { BackupMeta } from "@/api/types/backup";
import ScopeTags from "./ScopeTags";
import styles from "./BackupTable.module.less";

dayjs.extend(relativeTime);

// Backups are created manually, so total count stays low (typically < 100).
// Loading all at once and paginating client-side avoids backend complexity.
const PAGE_SIZE = 10;

interface Props {
  backups: BackupMeta[];
  searchQuery: string;
  onRestore: (backup: BackupMeta) => void;
  onRefresh: () => void;
}

export default function BackupTable({
  backups,
  searchQuery,
  onRestore,
  onRefresh,
}: Props) {
  const { t } = useTranslation();
  const { message } = useAppMessage();

  // Filter is applied to the full in-memory list so search covers all pages, not just the current one.
  const filteredBackups = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return backups;
    return backups.filter(
      (s) => s.name.toLowerCase().includes(q) || s.id.toLowerCase().includes(q),
    );
  }, [backups, searchQuery]);

  /** Deletes a single backup by ID and refreshes the list on success. */
  const handleDelete = async (id: string) => {
    try {
      await api.deleteBackups([id]);
      message.success(t("backup.deleteSuccess"));
      onRefresh();
    } catch {
      message.error(t("backup.deleteFailed"));
    }
  };

  /**
   * Shows a danger-confirmation modal warning the user about sensitive data
   * before triggering the zip download via the API.
   */
  const handleExport = (backup: BackupMeta) => {
    Modal.confirm({
      title: t("backup.exportWarningTitle"),
      content: t("backup.exportWarningContent"),
      okText: t("backup.exportConfirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        try {
          await api.exportBackup(backup.id, backup.name);
        } catch {
          message.error(t("backup.exportFailed"));
        }
      },
    });
  };

  const columns: ColumnsType<BackupMeta> = [
    {
      title: "ID",
      dataIndex: "id",
      key: "id",
      width: 300,
      render: (id: string) => <span className={styles.idCell}>{id}</span>,
    },
    {
      title: t("backup.name"),
      dataIndex: "name",
      key: "name",
      ellipsis: true,
    },
    {
      title: t("backup.scopeSummary"),
      key: "scope",
      width: 320,
      render: (_, record) => (
        <ScopeTags scope={record.scope} agentCount={record.agent_count} />
      ),
    },
    {
      title: t("backup.descriptionLabel"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
    },
    {
      title: t("backup.createdAt"),
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (val: string) => (
        <Tooltip title={dayjs(val).format("YYYY-MM-DD HH:mm:ss")}>
          {dayjs(val).fromNow()}
        </Tooltip>
      ),
      sorter: (a, b) => dayjs(a.created_at).unix() - dayjs(b.created_at).unix(),
      defaultSortOrder: "descend",
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 200,
      render: (_, record) => (
        <span className={styles.actions}>
          <Button type="link" size="small" onClick={() => onRestore(record)}>
            {t("backup.restore")}
          </Button>
          <Button type="link" size="small" onClick={() => handleExport(record)}>
            {t("backup.export")}
          </Button>
          <Popconfirm
            title={t("backup.deleteConfirm")}
            onConfirm={() => handleDelete(record.id)}
          >
            <Button type="link" size="small" danger>
              {t("backup.delete")}
            </Button>
          </Popconfirm>
        </span>
      ),
    },
  ];

  return (
    <Card className={styles.tableCard}>
      {backups.length === 0 ? (
        <Empty
          description={t("backup.noBackups")}
          style={{ padding: "40px 0" }}
        />
      ) : (
        <Table<BackupMeta>
          rowKey="id"
          dataSource={filteredBackups}
          columns={columns}
          size="middle"
          pagination={{
            pageSize: PAGE_SIZE,
            showSizeChanger: true,
            showTotal: (total) => t("backup.total", { count: total }),
            pageSizeOptions: ["10", "20", "50"],
          }}
        />
      )}
    </Card>
  );
}
