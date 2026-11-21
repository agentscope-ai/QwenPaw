/** Preserve the server verdict instead of treating a network outage as logout. */
import { interactionErrorText } from "../utils/interactionText";

export class AuthResponseError extends Error {
  readonly status: number;
  readonly rawMessage: string;
  readonly detail: unknown;
  constructor(message: string, status: number, detail?: unknown) {
    super(interactionErrorText(message, status));
    this.status = status;
    this.rawMessage = message;
    this.detail = detail;
    this.name = "AuthResponseError";
  }
}

export function isAuthenticationRejected(error: unknown): boolean {
  return (
    error instanceof AuthResponseError &&
    (error.status === 401 || error.status === 403)
  );
}
