export interface CreatorEvent<T = Record<string, unknown>> {
  eventId: string;
  seq: number;
  type: string;
  projectId: string;
  creatorSessionId: string;
  transactionId?: string;
  at: string;
  data: T;
}
