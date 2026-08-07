import { useTranslation } from "react-i18next";

export default function PageLoadError({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full items-center justify-center bg-[var(--color-bg-layout)] p-6">
      <div className="surface max-w-md p-5 text-center">
        <div className="text-sm font-semibold text-[var(--color-danger)]">
          {t("pageError.loadFailed")}
        </div>
        <p className="mt-2 text-xs text-[var(--color-text-secondary)]">
          {message}
        </p>
        <button onClick={retry} className="btn-secondary mt-4">
          {t("pageError.retry")}
        </button>
      </div>
    </div>
  );
}
