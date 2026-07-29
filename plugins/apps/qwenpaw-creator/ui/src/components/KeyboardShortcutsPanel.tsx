import { Modal } from "antd";

interface KeyboardShortcutsPanelProps {
  open: boolean;
  onClose: () => void;
}

interface ShortcutItem {
  keys: string[];
  description: string;
}

interface ShortcutGroup {
  title: string;
  shortcuts: ShortcutItem[];
}

const isMac =
  typeof navigator !== "undefined" &&
  /Mac|iPod|iPhone|iPad/.test(navigator.userAgent);
const modKey = isMac ? "⌘" : "Ctrl";

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    title: "通用",
    shortcuts: [
      { keys: [modKey, "S"], description: "保存项目" },
      { keys: ["?"], description: "打开快捷键面板" },
      { keys: ["Esc"], description: "关闭面板/弹窗" },
    ],
  },
  {
    title: "导航",
    shortcuts: [
      { keys: [modKey, "1"], description: "前往剧本大纲" },
      { keys: [modKey, "2"], description: "前往资产库" },
      { keys: [modKey, "4"], description: "前往视频" },
    ],
  },
];

function KbdKey({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-6 min-w-[24px] items-center justify-center rounded-md border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-1.5 font-mono text-xs text-[var(--color-text-primary)] shadow-sm">
      {children}
    </kbd>
  );
}

export default function KeyboardShortcutsPanel({
  open,
  onClose,
}: KeyboardShortcutsPanelProps) {
  return (
    <Modal
      title={
        <div className="flex items-center gap-2">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="text-[var(--color-text-secondary)]"
          >
            <rect x="2" y="4" width="20" height="16" rx="2" />
            <path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M6 12h.01M10 12h.01M14 12h.01M18 12h.01M8 16h8" />
          </svg>
          <span>键盘快捷键</span>
        </div>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={480}
      centered
      destroyOnHidden
    >
      <div className="mt-2 space-y-5">
        {SHORTCUT_GROUPS.map((group) => (
          <div key={group.title}>
            <h4 className="text-xs font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider mb-2">
              {group.title}
            </h4>
            <div className="space-y-1.5">
              {group.shortcuts.map((shortcut, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-[var(--color-bg-secondary)] transition-colors"
                >
                  <span className="text-sm text-[var(--color-text-primary)]">
                    {shortcut.description}
                  </span>
                  <div className="flex items-center gap-1">
                    {shortcut.keys.map((key, kidx) => (
                      <span key={kidx} className="flex items-center gap-0.5">
                        <KbdKey>{key}</KbdKey>
                        {kidx < shortcut.keys.length - 1 && (
                          <span className="text-[var(--color-text-tertiary)] text-xs mx-0.5">
                            +
                          </span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 pt-3 border-t border-[var(--color-border)] text-center">
        <span className="text-xs text-[var(--color-text-tertiary)]">
          按 <KbdKey>?</KbdKey> 随时打开此面板
        </span>
      </div>
    </Modal>
  );
}
