export const INTERNAL_QUEUE_REQUEST_ID_PARAM = "__qwenpaw_queue_request_id";

interface QueueRequestData {
  qwenpaw_queue_request_id?: unknown;
  biz_params?: Record<string, unknown>;
}

export function getQueueRequestId(data: QueueRequestData) {
  if (
    typeof data.qwenpaw_queue_request_id === "string" &&
    data.qwenpaw_queue_request_id
  ) {
    return data.qwenpaw_queue_request_id;
  }
  const requestId = data.biz_params?.[INTERNAL_QUEUE_REQUEST_ID_PARAM];
  return typeof requestId === "string" && requestId ? requestId : undefined;
}

export function shouldRestoreQueuedInputAfterError(
  data: QueueRequestData,
  acceptedRequestIds: ReadonlySet<string>,
) {
  const requestId = getQueueRequestId(data);
  return !requestId || !acceptedRequestIds.has(requestId);
}
