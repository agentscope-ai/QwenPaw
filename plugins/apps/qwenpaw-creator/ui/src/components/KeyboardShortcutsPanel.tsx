import { Modal } from "antd";
import { useTranslation } from "react-i18next";

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

function getShortcutGroups(t: (key: string) => string): ShortcutGroup[] {
  return [
    {
      title: t("keyboard.general"),
      shortcuts: [
        { keys: [modKey, "S"], description: t("keyboard.saveProject") },
        { keys: ["?"], description: t("keyboard.openShortcuts") },
        { keys: ["Esc"], description: t("keyboard.closePanel") },
      ],
    },
    {
      title: t("keyboard.navigation"),
      shortcuts: [
        { keys: [modKey, "1"], description: t("keyboard.goToScript") },
        { keys: [modKey, "2"], description: t("keyboard.goToAssets") },
        { keys: [modKey, "4"], description: t("keyboard.goToVideo") },
      ],
    },
  ];
}

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
  const { t } = useTranslation();
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
          <span>{t("keyboard.title")}</span>
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
        {getShortcutGroups(t).map((group) => (
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
          {t("keyboard.pressHint")} <KbdKey>?</KbdKey>{" "}
          {t("keyboard.openShortcuts")}
        </span>
      </div>
    </Modal>
  );
}
