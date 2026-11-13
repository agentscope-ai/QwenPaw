import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Check } from "lucide-react";

export function CodeBlockWithCopy({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    const code = wrapRef.current?.querySelector("code");
    const text = code?.textContent ?? "";
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div className="docs-code-wrap" ref={wrapRef}>
      <button
        type="button"
        className="docs-code-copy"
        onClick={handleCopy}
        aria-label={t("docs.copy")}
        title={t("docs.copy")}
      >
        {copied ? (
          <>
            <Check size={14} aria-hidden />
            <span>{t("docs.copied")}</span>
          </>
        ) : (
          <>
            <Copy size={14} aria-hidden />
            <span>{t("docs.copy")}</span>
          </>
        )}
      </button>
      {children}
    </div>
  );
}
