export type TranscriptionErrorCode = string;
export class TranscriptionError extends Error {
  status: number;
  code?: TranscriptionErrorCode;
  constructor(status: number, _message: string, code?: TranscriptionErrorCode) {
    super("Audio transcription failed");
    this.name = "TranscriptionError";
    this.status = status;
    this.code = code;
  }
}
