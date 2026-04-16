import { useState } from "react";
import { Card, Button, message } from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { meetingsApi } from "@/api/modules/meetings";
import type { Meeting, CreateMeetingRequest } from "@/api/types/meetings";
import { useMeetings } from "./useMeetings";
import {
  MeetingTable,
  MeetingDrawer,
  CreateMeetingModal,
  EditMeetingModal,
} from "./components";
import styles from "./index.module.less";

function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitleRow}>
          <h2 className={styles.sectionTitle}>{title}</h2>
        </div>
        {description && <p className={styles.sectionDesc}>{description}</p>}
      </div>
      {action && <div className={styles.sectionAction}>{action}</div>}
    </section>
  );
}

export default function MeetingsPage() {
  const { t } = useTranslation();
  const {
    meetings,
    loading,
    deleteMeeting,
    loadMeetings,
    startMeeting,
    stopMeeting,
    restartMeeting,
  } = useMeetings();

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedMeeting, setSelectedMeeting] = useState<Meeting | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [editingMeeting, setEditingMeeting] = useState<Meeting | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const handleRowClick = (meeting: Meeting) => {
    setSelectedMeeting(meeting);
    setDrawerOpen(true);
  };

  const handleView = (meeting: Meeting) => {
    setSelectedMeeting(meeting);
    setDrawerOpen(true);
  };

  const handleEdit = (meeting: Meeting) => {
    setEditingMeeting(meeting);
    setEditOpen(true);
  };

  const handleCreate = async (data: CreateMeetingRequest) => {
    setSubmitting(true);
    try {
      await meetingsApi.createMeeting(data);
      message.success(t("meetings.createSuccess"));
      setCreateOpen(false);
      await loadMeetings();
    } catch (err: any) {
      message.error(err.message || t("meetings.createFailed"));
      throw err;
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.meetingsPage}>
      <PageHeader
        title={t("meetings.title")}
        description={t("meetings.description")}
        action={
          <>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => loadMeetings()}
              loading={loading}
            >
              {t("common.refresh")}
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateOpen(true)}
              style={{ marginLeft: 8 }}
            >
              {t("meetings.create")}
            </Button>
          </>
        }
      />

      <Card className={styles.tableCard}>
        <MeetingTable
          meetings={meetings}
          loading={loading}
          onDelete={deleteMeeting}
          onStart={startMeeting}
          onStop={stopMeeting}
          onRestart={restartMeeting}
          onView={handleView}
          onEdit={handleEdit}
          onRowClick={handleRowClick}
        />
      </Card>

      <MeetingDrawer
        open={drawerOpen}
        meeting={selectedMeeting}
        onClose={() => setDrawerOpen(false)}
        onMeetingUpdated={loadMeetings}
      />

      <CreateMeetingModal
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onSubmit={handleCreate}
        submitting={submitting}
      />

      <EditMeetingModal
        open={editOpen}
        meeting={editingMeeting}
        onCancel={() => setEditOpen(false)}
        onUpdated={loadMeetings}
      />
    </div>
  );
}
