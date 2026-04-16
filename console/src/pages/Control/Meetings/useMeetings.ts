import { useState, useEffect } from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import { meetingsApi } from "@/api/modules/meetings";
import type { Meeting } from "@/api/types/meetings";

interface UseMeetingsReturn {
  meetings: Meeting[];
  loading: boolean;
  loadMeetings: () => Promise<void>;
  deleteMeeting: (meetingId: string) => Promise<void>;
  startMeeting: (meetingId: string) => Promise<void>;
  stopMeeting: (meetingId: string) => Promise<void>;
  restartMeeting: (meetingId: string) => Promise<void>;
}

export function useMeetings(): UseMeetingsReturn {
  const { t } = useTranslation();
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(false);

  const loadMeetings = async () => {
    setLoading(true);
    try {
      const data = await meetingsApi.listMeetings();
      setMeetings(data.meetings);
    } catch {
      message.error(t("meetings.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  const deleteMeeting = async (meetingId: string) => {
    try {
      await meetingsApi.deleteMeeting(meetingId);
      message.success(t("meetings.deleteSuccess"));
      await loadMeetings();
    } catch (err: any) {
      message.error(err.message || t("meetings.deleteFailed"));
      throw err;
    }
  };

  const startMeeting = async (meetingId: string) => {
    try {
      await meetingsApi.startMeeting(meetingId);
      message.success(t("meetings.startSuccess"));
      await loadMeetings();
    } catch (err: any) {
      message.error(err.message || t("meetings.startFailed"));
      throw err;
    }
  };

  const stopMeeting = async (meetingId: string) => {
    try {
      await meetingsApi.stopMeeting(meetingId);
      message.success(t("meetings.stopSuccess"));
      await loadMeetings();
    } catch (err: any) {
      message.error(err.message || t("meetings.stopFailed"));
      throw err;
    }
  };

  const restartMeeting = async (meetingId: string) => {
    try {
      await meetingsApi.restartMeeting(meetingId);
      message.success(t("meetings.restartSuccess"));
      await loadMeetings();
    } catch (err: any) {
      message.error(err.message || t("meetings.restartFailed"));
      throw err;
    }
  };

  useEffect(() => {
    loadMeetings();
  }, []);

  return {
    meetings,
    loading,
    loadMeetings,
    deleteMeeting,
    startMeeting,
    stopMeeting,
    restartMeeting,
  };
}
