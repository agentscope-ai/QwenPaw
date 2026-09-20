import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Plus, RotateCw, TerminalSquare, X } from "lucide-react";
import { Dropdown } from "antd";
import { Group, Panel, Separator, usePanelRef } from "react-resizable-panels";
import { useTranslation } from "react-i18next";
import { terminalGroup } from "./terminalIdentity";
import {
  terminalApi,
  type TerminalInfo,
  type TerminalScope,
} from "./terminalApi";
import styles from "./TerminalDock.module.less";

const TerminalView = lazy(() => import("./TerminalView"));

export default function TerminalDock({
  children,
  scope,
  isDark,
  open,
  setOpen,
}: {
  children: ReactNode;
  scope: TerminalScope;
  isDark: boolean;
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const group = terminalGroup(scope.agentId, scope.sessionId);
  const { t } = useTranslation();
  const panelRef = usePanelRef();
  const [height] = useState(() => {
    try {
      return Number(sessionStorage.getItem("qwenpaw-terminal-height")) || 250;
    } catch {
      return 250;
    }
  });
  const heightRef = useRef(height);
  useEffect(() => {
    if (open) panelRef.current?.resize(heightRef.current);
    else panelRef.current?.collapse();
  }, [open, panelRef]);
  return (
    <Group orientation="vertical" className={styles.layout}>
      <Panel id="conversation" minSize="30%" className={styles.chat}>
        {children}
      </Panel>
      {open && (
        <Separator
          className={styles.separator}
          aria-label={t("terminal.resize", "Resize terminal")}
        />
      )}
      <Panel
        id="terminal"
        panelRef={panelRef}
        collapsible
        collapsedSize={0}
        defaultSize={0}
        minSize={130}
        maxSize="65%"
        onResize={(size, _id, previous) => {
          if (
            open &&
            size.inPixels >= 130 &&
            previous &&
            previous.inPixels >= 130
          ) {
            heightRef.current = size.inPixels;
            try {
              sessionStorage.setItem(
                "qwenpaw-terminal-height",
                String(size.inPixels),
              );
            } catch {
              /* Optional preference. */
            }
          }
          if (
            open &&
            size.inPixels === 0 &&
            previous &&
            previous.inPixels >= 130
          ) {
            setOpen(false);
          }
        }}
      >
        <Dock
          key={group}
          group={group}
          scope={scope}
          isDark={isDark}
          open={open}
          setOpen={setOpen}
        />
      </Panel>
    </Group>
  );
}

function Dock({
  scope,
  group,
  isDark,
  open,
  setOpen,
}: {
  scope: TerminalScope;
  group: string;
  isDark: boolean;
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const { agentId, sessionId, chatId, projectDirOverride } = scope;
  const [tabs, setTabs] = useState<TerminalInfo[]>([]);
  const [active, setActive] = useState(() => {
    try {
      return sessionStorage.getItem(`qwenpaw-terminal-active:${group}`) || "";
    } catch {
      return "";
    }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [renaming, setRenaming] = useState("");
  const [title, setTitle] = useState("");
  const mounted = useRef(true);
  const operation = useRef(false);
  const revision = useRef(0);
  const api = useMemo(
    () =>
      terminalApi(
        { kind: "session", agentId, sessionId, chatId, projectDirOverride },
        group,
      ),
    [agentId, sessionId, chatId, projectDirOverride, group],
  );
  // Changes to a draft's persisted Chat ID should not interrupt terminal I/O.
  const io = useMemo(
    () => terminalApi({ kind: "session", agentId, sessionId: "new" }, group),
    [agentId, group],
  );
  const selected = tabs.find((tab) => tab.id === active) ?? tabs[0];
  useEffect(() => {
    if (selected) {
      try {
        sessionStorage.setItem(`qwenpaw-terminal-active:${group}`, selected.id);
      } catch {
        /* Optional preference. */
      }
    }
  }, [group, selected]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const refresh = (createIfEmpty = false) => {
      if (operation.current) return;
      const currentRevision = revision.current;
      void api
        .list(controller.signal)
        .then(async (next) => {
          if (
            !controller.signal.aborted &&
            !operation.current &&
            currentRevision === revision.current
          ) {
            setTabs(next);
            if (createIfEmpty && next.length === 0) {
              operation.current = true;
              revision.current += 1;
              setBusy(true);
              try {
                const tab = await api.create();
                if (mounted.current) {
                  setTabs([tab]);
                  setActive(tab.id);
                }
              } finally {
                operation.current = false;
                if (mounted.current) setBusy(false);
              }
            }
          }
        })
        .catch((cause) => {
          if (!controller.signal.aborted)
            setError(String(cause).split(" - ")[0]);
        });
    };
    refresh(true);
    const timer = window.setInterval(refresh, 60000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [api, open]);

  const run = async (action: () => Promise<void>) => {
    if (operation.current) return;
    operation.current = true;
    revision.current += 1;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (cause) {
      if (mounted.current) setError(String(cause).split(" - ")[0]);
    } finally {
      operation.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  const add = () => {
    setOpen(true);
    void run(async () => {
      const tab = await api.create();
      if (!mounted.current) return;
      setTabs((current) => [...current, tab]);
      setActive(tab.id);
      setOpen(true);
    });
  };
  const closeTabs = (ids: string[]) =>
    void run(async () => {
      let remaining = tabs;
      for (const id of ids) {
        await api.close(id);
        if (!mounted.current) return;
        remaining = remaining.filter((tab) => tab.id !== id);
        setTabs(remaining);
        if (remaining.length === 0) setOpen(false);
      }
    });
  const restart = () =>
    void run(async () => {
      if (!selected) return;
      await api.close(selected.id);
      if (mounted.current)
        setTabs((current) => current.filter((tab) => tab.id !== selected.id));
      const tab = await api.create();
      if (mounted.current) {
        setTabs((current) => [...current, tab]);
        setActive(tab.id);
      }
    });
  const rename = () => {
    const id = renaming;
    setRenaming("");
    if (!title.trim()) return;
    void run(async () => {
      const updated = await api.rename(id, title.trim());
      if (mounted.current)
        setTabs((current) =>
          current.map((tab) => (tab.id === id ? updated : tab)),
        );
    });
  };

  return (
    <section
      style={open ? undefined : { display: "none" }}
      className={styles.dock}
      aria-label={t("terminal.title", "Terminal")}
    >
      <div className={styles.toolbar}>
        <div
          role="tablist"
          className={styles.tabs}
          aria-label={t("terminal.tabs", "Terminal tabs")}
        >
          {tabs.map((tab, index) => (
            <Dropdown
              key={tab.id}
              trigger={["contextMenu"]}
              menu={{
                items: [
                  {
                    key: "current",
                    label: t("terminal.close", "Close terminal"),
                    disabled: busy,
                  },
                  {
                    key: "others",
                    label: t("terminal.closeOthers", "Close other terminals"),
                    disabled: busy || tabs.length < 2,
                  },
                  { type: "divider" },
                  {
                    key: "all",
                    label: t("terminal.closeAll", "Close all terminals"),
                    disabled: busy,
                    danger: true,
                  },
                ],
                onClick: ({ key }) =>
                  closeTabs(
                    tabs
                      .filter(
                        (item) =>
                          key === "all" ||
                          (key === "others"
                            ? item.id !== tab.id
                            : item.id === tab.id),
                      )
                      .map((item) => item.id),
                  ),
              }}
            >
              <div className={styles.tab} data-active={selected?.id === tab.id}>
                {renaming === tab.id ? (
                  <input
                    aria-label={t("terminal.rename", "Rename terminal")}
                    autoFocus
                    maxLength={64}
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    onBlur={rename}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") event.currentTarget.blur();
                      if (event.key === "Escape") setRenaming("");
                    }}
                  />
                ) : (
                  <button
                    className={styles.tabLabel}
                    role="tab"
                    aria-selected={selected?.id === tab.id}
                    title={tab.cwd}
                    onDoubleClick={() => {
                      setRenaming(tab.id);
                      setTitle(tab.title);
                    }}
                    onClick={() => {
                      setActive(tab.id);
                      setOpen(true);
                    }}
                  >
                    <TerminalSquare size={15} aria-hidden="true" />
                    <span>
                      {tab.title} {index + 1}
                    </span>
                  </button>
                )}
                <button
                  disabled={busy}
                  aria-label={`${t("terminal.close", "Close terminal")} ${
                    index + 1
                  }`}
                  onClick={() => closeTabs([tab.id])}
                >
                  <X size={12} />
                </button>
              </div>
            </Dropdown>
          ))}
        </div>
        <button
          disabled={busy || tabs.length >= 8}
          aria-label={t("terminal.new", "New terminal")}
          title={t("terminal.new", "New terminal")}
          onClick={add}
        >
          <Plus size={16} />
        </button>
        {open && selected?.exited && (
          <button
            disabled={busy}
            aria-label={t("terminal.restart", "Restart terminal")}
            title={t("terminal.restart", "Restart terminal")}
            onClick={restart}
          >
            <RotateCw size={14} />
          </button>
        )}
        <button
          className={styles.collapse}
          aria-label={t("terminal.hide", "Hide terminal panel")}
          title={t("terminal.hide", "Hide terminal panel")}
          onClick={() => setOpen(false)}
        >
          <X size={16} />
        </button>
      </div>
      {open && (
        <>
          {error && (
            <div role="alert" className={styles.status}>
              {error}
              <button onClick={() => setError("")}>
                <X size={12} />
              </button>
            </div>
          )}
          {selected ? (
            <Suspense
              fallback={
                <div className={styles.empty}>
                  {t("common.loading", "Loading…")}
                </div>
              }
            >
              <TerminalView
                key={selected.id}
                terminal={selected}
                api={io}
                isDark={isDark}
              />
            </Suspense>
          ) : (
            <div className={styles.empty}>
              <button disabled={busy} onClick={add}>
                <Plus size={16} />
                {t("terminal.new", "New terminal")}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
