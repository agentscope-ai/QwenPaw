export type UploadStatusPhase =
  | "uploading"
  | "processing"
  | "success"
  | "error";

export type UploadStatusMessages = {
  uploading: (fileName: string) => string;
  uploaded: (fileName: string) => string;
  processing: (fileName: string) => string;
  processingSlow: (fileName: string) => string;
  success: (fileName: string) => string;
};

export type UploadStatusState = {
  fileName: string;
  phase: UploadStatusPhase;
  busy: boolean;
  label: string;
};

export function createUploadStatusState(
  fileName: string,
  messages: UploadStatusMessages,
): UploadStatusState {
  return {
    fileName,
    phase: "uploading",
    busy: true,
    label: messages.uploading(fileName),
  };
}

export function markUploadCompleted(
  state: UploadStatusState,
  messages: UploadStatusMessages,
): UploadStatusState {
  return {
    ...state,
    phase: "processing",
    busy: true,
    label: messages.uploaded(state.fileName),
  };
}

export function markProcessingStarted(
  state: UploadStatusState,
  messages: UploadStatusMessages,
): UploadStatusState {
  return {
    ...state,
    phase: "processing",
    busy: true,
    label: messages.processing(state.fileName),
  };
}

export function markProcessingSlow(
  state: UploadStatusState,
  messages: UploadStatusMessages,
): UploadStatusState {
  return {
    ...state,
    phase: "processing",
    busy: true,
    label: messages.processingSlow(state.fileName),
  };
}

export function markUploadSucceeded(
  state: UploadStatusState,
  messages: UploadStatusMessages,
): UploadStatusState {
  return {
    ...state,
    phase: "success",
    busy: false,
    label: messages.success(state.fileName),
  };
}

export function markUploadFailed(
  state: UploadStatusState,
  message: string,
): UploadStatusState {
  return {
    ...state,
    phase: "error",
    busy: false,
    label: message,
  };
}

export function shouldShowUploadToast(phase: UploadStatusPhase): boolean {
  return phase === "error";
}
