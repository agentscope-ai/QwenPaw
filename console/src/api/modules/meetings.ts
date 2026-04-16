import { request } from "../request";
import type {
  Meeting,
  MeetingListResponse,
  CreateMeetingRequest,
  MeetingDocContent,
  MeetingStatusResponse,
  MeetingReasonsResponse,
} from "../types/meetings";

export const meetingsApi = {
  listMeetings: (skip = 0, limit = 100) =>
    request<MeetingListResponse>(`/meetings?skip=${skip}&limit=${limit}`),

  getMeeting: (meetingId: string) => request<Meeting>(`/meetings/${meetingId}`),

  createMeeting: (data: CreateMeetingRequest) =>
    request<Meeting>("/meetings", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteMeeting: (meetingId: string) =>
    request<{ status: string; meeting_id: string }>(`/meetings/${meetingId}`, {
      method: "DELETE",
    }),

  startMeeting: (meetingId: string) =>
    request<{ status: string; meeting_id: string; result?: unknown }>(
      `/meetings/${meetingId}/start`,
      { method: "POST" },
    ),

  stopMeeting: (meetingId: string) =>
    request<{ status: string; meeting_id: string }>(
      `/meetings/${meetingId}/stop`,
      {
        method: "POST",
      },
    ),

  restartMeeting: (meetingId: string) =>
    request<{ status: string; meeting_id: string; result?: unknown }>(
      `/meetings/${meetingId}/restart`,
      { method: "POST" },
    ),

  getMeetingStatus: (meetingId: string) =>
    request<MeetingStatusResponse>(`/meetings/${meetingId}/status`),

  getMeetingGoals: (meetingId: string) =>
    request<MeetingDocContent>(`/meetings/${meetingId}/goals`),

  getMeetingRecords: (meetingId: string) =>
    request<MeetingDocContent>(`/meetings/${meetingId}/records`),

  getMeetingSummary: (meetingId: string) =>
    request<MeetingDocContent>(`/meetings/${meetingId}/summary`),

  getMeetingReasons: (meetingId: string) =>
    request<MeetingReasonsResponse>(`/meetings/${meetingId}/reasons`),

  updateMeeting: (
    meetingId: string,
    data: Partial<{
      meeting_name: string;
      topic: { title: string; description?: string; context?: string };
    }>,
  ) =>
    request(`/meetings/${meetingId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
};
