export type MeetingType = "REGULAR" | "TEMPORARY";

export type MeetingStatus =
  | "CREATED"
  | "INITIALIZED"
  | "RUNNING"
  | "COMPLETED"
  | "STOPPED"
  | "FAILED";

export type RoleType = "HOST" | "REPORTER" | "DECIDER" | "OBSERVER";

export interface MeetingTopic {
  title: string;
  description?: string;
  context?: string;
}

export interface ParticipantEndpoint {
  url: string;
  auth_key: string;
}

export interface MeetingParticipant {
  id: string;
  name: string;
  intent?: string;
  endpoint?: ParticipantEndpoint;
}

export interface Meeting {
  meeting_id: string;
  meeting_name: string;
  meeting_type: MeetingType;
  status: MeetingStatus;
  topic_title?: string;
  topic?: MeetingTopic;
  participants: MeetingParticipant[];
  participants_count?: number;
  documents?: {
    goals_path?: string;
    records_path?: string;
    summary_path?: string;
  };
  current_round?: number;
  current_phase?: string;
  created_at?: string;
}

export interface MeetingListResponse {
  meetings: Meeting[];
  total: number;
  skip: number;
  limit: number;
}

export interface CreateMeetingRequest {
  meeting_name: string;
  meeting_type: MeetingType;
  topic: MeetingTopic;
  participants: MeetingParticipant[];
  host_id: string;
  decider_id: string;
  rounds: string[];
}

export interface MeetingDocContent {
  meeting_id: string;
  goals_path?: string;
  records_path?: string;
  summary_path?: string;
  content: string;
}

export interface MeetingStatusResponse {
  meeting_id: string;
  status: MeetingStatus;
  current_round: number;
  current_phase: string | null;
}

export interface ReasonEntry {
  时间: string;
  阶段: string;
  发言人: string;
  发言内容: string;
  reasons: string[];
}

export interface MeetingReasonsResponse {
  meeting_id: string;
  reasons_path: string;
  entries: ReasonEntry[];
}
