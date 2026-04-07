import { useState, useEffect } from "react";
import {
  Drawer,
  Tag,
  Spin,
  Empty,
  Button,
  Space,
  message,
  Modal,
  Tabs,
  Input,
  Select,
} from "antd";
import {
  PlayCircleOutlined,
  StopOutlined,
  DownloadOutlined,
  ReloadOutlined,
  FileTextOutlined,
  BulbOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { meetingsApi } from "@/api/modules/meetings";
import type { Meeting, MeetingStatus, ReasonEntry } from "@/api/types/meetings";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";

interface MeetingDrawerProps {
  open: boolean;
  meeting: Meeting | null;
  onClose: () => void;
  onMeetingUpdated?: () => void;
}

const STATUS_COLOR: Record<MeetingStatus, string> = {
  CREATED: "default",
  INITIALIZED: "processing",
  RUNNING: "processing",
  COMPLETED: "success",
  STOPPED: "warning",
  FAILED: "error",
};

function LoadingState() {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: 48 }}>
      <Spin />
    </div>
  );
}

export function MeetingDrawer({
  open,
  meeting,
  onClose,
  onMeetingUpdated,
}: MeetingDrawerProps) {
  const { t } = useTranslation();
  const [background, setBackground] = useState("");
  const [records, setRecords] = useState("");
  const [summary, setSummary] = useState("");
  const [reasons, setReasons] = useState<ReasonEntry[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [recordsModalOpen, setRecordsModalOpen] = useState(false);

  // 思考过程相关状态
  const [speakerFilter, setSpeakerFilter] = useState<string>("");
  const [phaseFilter, setPhaseFilter] = useState<string>("");
  const [searchText, setSearchText] = useState<string>("");
  const [reasonsModalOpen, setReasonsModalOpen] = useState(false);
  const [selectedReasonEntry, setSelectedReasonEntry] =
    useState<ReasonEntry | null>(null);

  const loadDocs = () => {
    if (!open || !meeting) return;

    setBackground("");
    setRecords("");
    setSummary("");
    setReasons([]);
    setLoadingDocs(true);

    Promise.allSettled([
      meetingsApi.getMeetingGoals(meeting.meeting_id),
      meetingsApi.getMeetingRecords(meeting.meeting_id),
      meetingsApi.getMeetingSummary(meeting.meeting_id),
      meetingsApi.getMeetingReasons(meeting.meeting_id),
    ]).then(([bg, rec, sum, reasonsRes]) => {
      if (bg.status === "fulfilled") setBackground(bg.value.content ?? "");
      if (rec.status === "fulfilled") setRecords(rec.value.content ?? "");
      if (sum.status === "fulfilled") setSummary(sum.value.content ?? "");
      if (reasonsRes.status === "fulfilled")
        setReasons(reasonsRes.value.entries ?? []);
      setLoadingDocs(false);
    });
  };

  const handleStartMeeting = async () => {
    if (!meeting) return;
    setStarting(true);
    try {
      await meetingsApi.startMeeting(meeting.meeting_id);
      message.success(t("meetings.startMeeting") + " " + t("common.success"));
      onMeetingUpdated?.();
    } catch {
      message.error(t("meetings.createFailed"));
    } finally {
      setStarting(false);
    }
  };

  const handleStopMeeting = async () => {
    if (!meeting) return;
    setStopping(true);
    try {
      await meetingsApi.stopMeeting(meeting.meeting_id);
      message.success(t("meetings.stopMeeting") + " " + t("common.success"));
      onMeetingUpdated?.();
    } catch {
      message.error(t("meetings.deleteFailed"));
    } finally {
      setStopping(false);
    }
  };

  const handleExportZip = async () => {
    if (!meeting) return;
    setExporting(true);
    try {
      const [goalsRes, recordsRes, summaryRes] = await Promise.allSettled([
        meetingsApi.getMeetingGoals(meeting.meeting_id),
        meetingsApi.getMeetingRecords(meeting.meeting_id),
        meetingsApi.getMeetingSummary(meeting.meeting_id),
      ]);

      const goals =
        goalsRes.status === "fulfilled" ? goalsRes.value.content : "";
      const recordsContent =
        recordsRes.status === "fulfilled" ? recordsRes.value.content : "";
      const summaryContent =
        summaryRes.status === "fulfilled" ? summaryRes.value.content : "";

      const zip = new (window as any).JSZip();
      if (goals) zip.file("goals.md", goals);
      if (recordsContent) zip.file("records.md", recordsContent);
      if (summaryContent) zip.file("summary.md", summaryContent);

      const blob = await zip.generateAsync({ type: "blob" });

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${meeting.meeting_name || meeting.meeting_id}_meeting.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      message.success(t("common.exportSuccess") || "导出成功");
    } catch (err) {
      message.error(t("common.exportFailed") || "导出失败");
      console.error("Export error:", err);
    } finally {
      setExporting(false);
    }
  };

  useEffect(() => {
    if (!open || !meeting) {
      setBackground("");
      setRecords("");
      setSummary("");
      setReasons([]);
      setLoadingDocs(false);
      setRecordsModalOpen(false);
      setSpeakerFilter("");
      setPhaseFilter("");
      setSearchText("");
      setReasonsModalOpen(false);
      setSelectedReasonEntry(null);
      return;
    }

    loadDocs();
  }, [open, meeting?.meeting_id]);

  // 打开思考过程详情模态框
  const handleOpenReasonDetail = (entry: ReasonEntry) => {
    setSelectedReasonEntry(entry);
    setReasonsModalOpen(true);
  };

  // 获取唯一发言人和阶段列表
  const speakers = Array.from(
    new Set(reasons.map((r) => r.发言人).filter(Boolean)),
  );
  const phases = Array.from(
    new Set(reasons.map((r) => r.阶段).filter(Boolean)),
  );

  // 过滤后的数据
  const filteredReasons = reasons.filter((r) => {
    const matchSpeaker = !speakerFilter || r.发言人 === speakerFilter;
    const matchPhase = !phaseFilter || r.阶段 === phaseFilter;
    const matchSearch =
      !searchText ||
      r.发言内容.toLowerCase().includes(searchText.toLowerCase()) ||
      r.reasons.some((s) => s.toLowerCase().includes(searchText.toLowerCase()));
    return matchSpeaker && matchPhase && matchSearch;
  });

  const status = meeting?.status as MeetingStatus | undefined;
  const canStart = status === "CREATED" || status === "INITIALIZED";
  const canStop = status === "RUNNING";

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        width={800}
        title={
          meeting ? (
            <span>
              {meeting.meeting_name}
              {status && (
                <Tag color={STATUS_COLOR[status]} style={{ marginLeft: 8 }}>
                  {status}
                </Tag>
              )}
            </span>
          ) : null
        }
        extra={
          <Space>
            {canStart && (
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={starting}
                onClick={handleStartMeeting}
              >
                {t("meetings.startMeeting")}
              </Button>
            )}
            {canStop && (
              <Button
                danger
                icon={<StopOutlined />}
                loading={stopping}
                onClick={handleStopMeeting}
              >
                {t("meetings.stopMeeting")}
              </Button>
            )}
            <Button
              icon={<DownloadOutlined />}
              loading={exporting}
              onClick={handleExportZip}
            >
              {t("common.export") || "导出"}
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={loadDocs}
              loading={loadingDocs}
            />
          </Space>
        }
        destroyOnClose
      >
        {loadingDocs ? (
          <LoadingState />
        ) : (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              height: "calc(100vh - 180px)",
            }}
          >
            {/* 可滚动内容区 - 使用 Tabs 组织 */}
            <div style={{ flex: 1, overflowY: "auto" }}>
              <Tabs
                defaultActiveKey="background"
                items={[
                  {
                    key: "background",
                    label: "会议背景",
                    children: (
                      <div style={{ maxHeight: "55vh", overflowY: "auto" }}>
                        {background ? (
                          <MarkdownRenderer content={background} />
                        ) : (
                          <Empty description={t("meetings.noContent")} />
                        )}
                      </div>
                    ),
                  },
                  {
                    key: "summary",
                    label: "会议总结",
                    children: (
                      <div style={{ maxHeight: "55vh", overflowY: "auto" }}>
                        {summary ? (
                          <MarkdownRenderer content={summary} />
                        ) : (
                          <Empty description={t("meetings.noContent")} />
                        )}
                      </div>
                    ),
                  },
                  {
                    key: "reasons",
                    label: (
                      <span>
                        <BulbOutlined style={{ marginRight: 4 }} />
                        思考过程
                      </span>
                    ),
                    children: (
                      <div>
                        {/* 过滤控件 */}
                        <div
                          style={{
                            display: "flex",
                            gap: 8,
                            marginBottom: 12,
                            flexWrap: "wrap",
                          }}
                        >
                          <Input
                            placeholder="搜索发言内容或思考过程"
                            value={searchText}
                            onChange={(e) => setSearchText(e.target.value)}
                            style={{ width: 200 }}
                            allowClear
                          />
                          <Select
                            placeholder="发言人"
                            value={speakerFilter || undefined}
                            onChange={(v) => setSpeakerFilter(v || "")}
                            allowClear
                            style={{ width: 120 }}
                          >
                            {speakers.map((s) => (
                              <Select.Option key={s} value={s}>
                                {s}
                              </Select.Option>
                            ))}
                          </Select>
                          <Select
                            placeholder="阶段"
                            value={phaseFilter || undefined}
                            onChange={(v) => setPhaseFilter(v || "")}
                            allowClear
                            style={{ width: 150 }}
                          >
                            {phases.map((p) => (
                              <Select.Option key={p} value={p}>
                                {p}
                              </Select.Option>
                            ))}
                          </Select>
                          <span
                            style={{
                              color: "#999",
                              fontSize: 12,
                              alignSelf: "center",
                            }}
                          >
                            共 {filteredReasons.length} 条记录
                          </span>
                        </div>
                        {/* 思考过程列表 - 只显示步骤数量 */}
                        <div
                          style={{
                            maxHeight: "calc(55vh - 60px)",
                            overflowY: "auto",
                          }}
                        >
                          {filteredReasons.length > 0 ? (
                            filteredReasons.map((entry, idx) => (
                              <div
                                key={idx}
                                onClick={() => handleOpenReasonDetail(entry)}
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "space-between",
                                  padding: "10px 12px",
                                  marginBottom: 8,
                                  background: "#f5f5f5",
                                  borderRadius: 6,
                                  cursor: "pointer",
                                  transition: "background 0.2s",
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.background = "#e8e8e8";
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.background = "#f5f5f5";
                                }}
                              >
                                <div style={{ flex: 1, overflow: "hidden" }}>
                                  <div
                                    style={{
                                      fontSize: 13,
                                      color: "#333",
                                      marginBottom: 2,
                                      overflow: "hidden",
                                      display: "-webkit-box",
                                      WebkitLineClamp: 5,
                                      WebkitBoxOrient: "vertical",
                                    }}
                                  >
                                    <MarkdownRenderer
                                      content={entry.发言内容}
                                    />
                                  </div>
                                  <div style={{ fontSize: 12, color: "#999" }}>
                                    <span style={{ marginRight: 12 }}>
                                      {entry.发言人}
                                    </span>
                                    <span>{entry.阶段}</span>
                                  </div>
                                </div>
                                <div
                                  style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    minWidth: 50,
                                    marginLeft: 12,
                                  }}
                                >
                                  <span
                                    style={{
                                      fontSize: 20,
                                      fontWeight: 600,
                                      color: "#1890ff",
                                    }}
                                  >
                                    {entry.reasons?.length || 0}
                                  </span>
                                  <span style={{ fontSize: 11, color: "#999" }}>
                                    步骤
                                  </span>
                                </div>
                              </div>
                            ))
                          ) : (
                            <Empty description="暂无思考过程数据" />
                          )}
                        </div>
                      </div>
                    ),
                  },
                ]}
              />
            </div>

            {/* 固定在底部的按钮 */}
            <div
              style={{
                paddingTop: 16,
                borderTop: "1px solid #f0f0f0",
                textAlign: "center",
                flexShrink: 0,
              }}
            >
              <Button
                type="dashed"
                icon={<FileTextOutlined />}
                size="large"
                onClick={() => setRecordsModalOpen(true)}
              >
                查看会议记录
              </Button>
            </div>
          </div>
        )}
      </Drawer>

      {/* 会议记录 Modal */}
      <Modal
        title="会议记录"
        open={recordsModalOpen}
        onCancel={() => setRecordsModalOpen(false)}
        footer={null}
        width={900}
        destroyOnClose
      >
        <div
          style={{
            maxHeight: "70vh",
            overflow: "auto",
            padding: "8px 0",
          }}
        >
          {records ? (
            <MarkdownRenderer content={records} />
          ) : (
            <Empty description={t("meetings.noContent")} />
          )}
        </div>
      </Modal>

      {/* 思考过程详情 Modal */}
      <Modal
        title={
          selectedReasonEntry ? (
            <div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>
                <MarkdownRenderer content={selectedReasonEntry.发言内容} />
              </div>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 400,
                  color: "#999",
                  marginTop: 4,
                }}
              >
                {selectedReasonEntry.发言人} · {selectedReasonEntry.阶段} ·{" "}
                {selectedReasonEntry.时间}
              </div>
            </div>
          ) : (
            "思考过程详情"
          )
        }
        open={reasonsModalOpen}
        onCancel={() => {
          setReasonsModalOpen(false);
          setSelectedReasonEntry(null);
        }}
        footer={null}
        width={700}
        destroyOnClose
      >
        <div
          style={{
            maxHeight: "60vh",
            overflowY: "auto",
            padding: "8px 0",
          }}
        >
          {selectedReasonEntry?.reasons &&
          selectedReasonEntry.reasons.length > 0 ? (
            <div>
              <div style={{ marginBottom: 16, color: "#666", fontSize: 13 }}>
                共 {selectedReasonEntry.reasons.length} 步思考过程
              </div>
              <div
                style={{
                  borderLeft: "3px solid #1890ff",
                  paddingLeft: 16,
                }}
              >
                {selectedReasonEntry.reasons.map((reason, idx) => (
                  <div
                    key={idx}
                    style={{
                      position: "relative",
                      paddingBottom:
                        idx < selectedReasonEntry.reasons.length - 1 ? 20 : 0,
                    }}
                  >
                    {/* 步骤圆点 */}
                    <div
                      style={{
                        position: "absolute",
                        left: -25,
                        top: 4,
                        width: 16,
                        height: 16,
                        borderRadius: "50%",
                        background: "#1890ff",
                        color: "#fff",
                        fontSize: 10,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 600,
                      }}
                    >
                      {idx + 1}
                    </div>
                    {/* 步骤内容 - Markdown渲染 */}
                    <div
                      style={{
                        background: "#f8f8f8",
                        borderRadius: 6,
                        padding: "12px 16px",
                        fontSize: 13,
                        lineHeight: 1.7,
                        color: "#333",
                      }}
                    >
                      <MarkdownRenderer content={reason} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <Empty description="无思考过程数据" />
          )}
        </div>
      </Modal>
    </>
  );
}
