import { request } from "../request";

export type MigrationDomainStatus =
  | "ready"
  | "empty"
  | "rejected"
  | "unavailable";

export interface MigrationIssue {
  code: string;
  source: string;
  detail: string;
}

export interface MigrationDomain {
  key: string;
  label: string;
  status: MigrationDomainStatus;
  count: number;
  source_hash: string;
  mapping: Record<string, string>;
  conflicts: MigrationIssue[];
  rejected: MigrationIssue[];
}

export interface MigrationPreview {
  generated_at: string;
  read_only: true;
  summary: {
    domain_count: number;
    item_count: number;
    conflict_count: number;
    rejected_count: number;
    secret_reference_count: number;
  };
  integrity: {
    before_hash: string;
    after_hash: string;
    unchanged: boolean;
  };
  domains: MigrationDomain[];
  secret_references: Array<{
    reference: string;
    version: "fernet-v1" | "plaintext" | "unknown";
    value_exposed: false;
  }>;
}

export const migrationApi = {
  getPreview: () =>
    request<MigrationPreview>("/migration/preview", { method: "GET" }),
};
