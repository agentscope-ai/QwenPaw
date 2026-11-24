// @vitest-environment jsdom
import type { ComponentProps, ReactNode } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BackupMeta } from "@/api/types/backup";

const mocks = vi.hoisted(() => ({
  getActiveBackupJob: vi.fn(),
  listAgents: vi.fn(),
  listBackups: vi.fn(),
  handleImport: vi.fn(),
  handleRestore: vi.fn(),
  tableProps: null as {
    backups: BackupMeta[];
    onRefresh: () => void;
  } | null,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/api", () => ({
  default: {
    getActiveBackupJob: (...args: unknown[]) =>
      mocks.getActiveBackupJob(...args),
    listBackups: (...args: unknown[]) => mocks.listBackups(...args),
  },
  agentsApi: {
    listAgents: (...args: unknown[]) => mocks.listAgents(...args),
  },
}));

vi.mock("antd", () => ({
  Button: ({
    children,
    icon,
    ...props
  }: ComponentProps<"button"> & {
    icon?: ReactNode;
  }) => (
    <button type="button" {...props}>
      {icon}
      {children}
    </button>
  ),
  Spin: () => <div data-testid="loading" />,
}));

vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({
    current,
    extra,
  }: {
    current: ReactNode;
    extra: ReactNode;
  }) => (
    <header>
      {current}
      {extra}
    </header>
  ),
}));

vi.mock("./list/BackupToolbar", () => ({
  default: () => <div data-testid="backup-toolbar" />,
}));

vi.mock("./list/BackupTable", () => ({
  default: (props: { backups: BackupMeta[]; onRefresh: () => void }) => {
    mocks.tableProps = props;
    return <div data-testid="backup-table">{props.backups.length}</div>;
  },
}));

vi.mock("./import/ImportButton", () => ({
  default: ({ onPick }: { onPick: (file: File) => void }) => (
    <button onClick={() => onPick(new File(["x"], "backup.zip"))}>
      backup.import
    </button>
  ),
}));

vi.mock("./import/useImportFlow", () => ({
  useImportFlow: () => ({
    clearConflict: vi.fn(),
    clearTrust: vi.fn(),
    conflictMeta: null,
    handleConflictChoice: vi.fn(),
    handleImport: mocks.handleImport,
    handleTrustConfirm: vi.fn(),
    trustFileName: null,
    trustLoading: false,
    trustMode: null,
  }),
}));

vi.mock("./restore/useRestoreFlow", () => ({
  useRestoreFlow: () => ({
    cancelPreRestore: vi.fn(),
    confirmRestoreWithBackup: vi.fn(),
    confirmRestoreWithoutBackup: vi.fn(),
    handleRestore: mocks.handleRestore,
    onPreRestoreBackupClose: vi.fn(),
    onPreRestoreBackupSuccess: vi.fn(),
    preRestoreBackupTarget: null,
    preRestoreConfirmTarget: null,
    restoreTarget: null,
    setRestoreTarget: vi.fn(),
  }),
}));

vi.mock("./import/ImportConflictModal", () => ({ default: () => null }));
vi.mock("./trust/BackupTrustDialog", () => ({ default: () => null }));
vi.mock("./create/CreateBackupModal", () => ({
  default: ({ open }: { open: boolean }) =>
    open ? <div data-testid="create-modal" /> : null,
}));
vi.mock("./create/SilentBackupModal", () => ({ default: () => null }));
vi.mock("./restore/PreRestoreConfirmModal", () => ({ default: () => null }));
vi.mock("./restore/RestoreBackupModal", () => ({ default: () => null }));

import BackupsPage from "./index";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function backup(id: string): BackupMeta {
  return {
    id,
    name: id,
    description: "",
    created_at: "2026-10-19T00:00:00Z",
    agent_count: 0,
    scope: {
      include_agents: false,
      include_global_config: false,
      include_secrets: false,
      include_skill_pool: false,
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.tableProps = null;
  mocks.listAgents.mockResolvedValue({ agents: [] });
  mocks.getActiveBackupJob.mockResolvedValue(null);
  mocks.listBackups.mockResolvedValue([]);
});

describe("BackupsPage load recovery", () => {
  it("blocks jobs on failure and retries into a successful empty state", async () => {
    mocks.listBackups
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce([]);
    render(<BackupsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "backup.loadFailed",
    );
    expect(screen.queryByRole("button", { name: "backup.import" })).toBeNull();
    expect(screen.queryByRole("button", { name: "backup.create" })).toBeNull();
    expect(screen.queryByTestId("backup-table")).toBeNull();
    expect(mocks.handleImport).not.toHaveBeenCalled();
    expect(mocks.handleRestore).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));

    expect(await screen.findByTestId("backup-table")).toHaveTextContent("0");
    expect(screen.getByRole("button", { name: "backup.import" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "backup.create" })).toBeEnabled();
  });

  it("does not expose job actions before the initial request succeeds", () => {
    mocks.listBackups.mockReturnValue(new Promise(() => {}));
    render(<BackupsPage />);

    expect(screen.getByTestId("loading")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "backup.import" })).toBeNull();
    expect(screen.queryByRole("button", { name: "backup.create" })).toBeNull();
  });

  it("ignores an older refresh that settles after the latest request", async () => {
    mocks.listBackups.mockResolvedValueOnce([backup("initial")]);
    render(<BackupsPage />);
    expect(await screen.findByTestId("backup-table")).toHaveTextContent("1");

    const older = deferred<BackupMeta[]>();
    const latest = deferred<BackupMeta[]>();
    mocks.listBackups
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(latest.promise);
    const refresh = mocks.tableProps!.onRefresh;
    act(() => {
      refresh();
      refresh();
    });

    await act(async () => {
      latest.resolve([backup("latest"), backup("latest-2")]);
      await latest.promise;
    });
    await waitFor(() =>
      expect(screen.getByTestId("backup-table")).toHaveTextContent("2"),
    );

    await act(async () => {
      older.resolve([backup("stale")]);
      await older.promise;
    });
    expect(screen.getByTestId("backup-table")).toHaveTextContent("2");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ignores an older refresh failure after the latest request succeeds", async () => {
    mocks.listBackups.mockResolvedValueOnce([backup("initial")]);
    render(<BackupsPage />);
    expect(await screen.findByTestId("backup-table")).toBeInTheDocument();

    const older = deferred<BackupMeta[]>();
    const latest = deferred<BackupMeta[]>();
    mocks.listBackups
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(latest.promise);
    const refresh = mocks.tableProps!.onRefresh;
    act(() => {
      refresh();
      refresh();
    });

    await act(async () => {
      latest.resolve([backup("latest")]);
      await latest.promise;
    });
    await waitFor(() =>
      expect(screen.getByTestId("backup-table")).toHaveTextContent("1"),
    );

    await act(async () => {
      older.reject(new Error("stale offline"));
      await older.promise.catch(() => undefined);
    });
    expect(screen.getByTestId("backup-table")).toHaveTextContent("1");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
