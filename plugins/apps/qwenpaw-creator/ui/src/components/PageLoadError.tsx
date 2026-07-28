export default function PageLoadError({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="flex h-full items-center justify-center bg-[var(--color-bg-layout)] p-6">
      <div className="surface max-w-md p-5 text-center">
        <div className="text-sm font-semibold text-[var(--color-danger)]">
          页面 View 加载失败
        </div>
        <p className="mt-2 text-xs text-[var(--color-text-secondary)]">
          {message}
        </p>
        <button onClick={retry} className="btn-secondary mt-4">
          重试
        </button>
      </div>
    </div>
  );
}
