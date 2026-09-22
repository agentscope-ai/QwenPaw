import type { ReactElement, ReactNode } from "react";
import { ArrowUpRight, Sparkles } from "lucide-react";
import styles from "./ChatWelcome.module.less";

export function ChatWelcome({
  greeting,
  description,
  avatar,
  prompts,
  onSubmit,
}: {
  greeting?: ReactNode;
  description?: ReactNode;
  avatar?: ReactNode;
  prompts?: (
    | string
    | { label?: ReactNode; value: string; icon?: ReactElement }
  )[];
  onSubmit: (data: { query: string }) => void;
}) {
  return (
    <section className={styles.welcome}>
      {typeof avatar === "string" ? (
        <img src={avatar} alt="" className={styles.avatar} />
      ) : (
        avatar
      )}
      <h1>{greeting}</h1>
      {description && <p>{description}</p>}
      {!!prompts?.length && (
        <div className={styles.prompts}>
          {prompts.map((item) => {
            const prompt = typeof item === "string" ? { value: item } : item;
            return (
              <button
                key={prompt.value}
                type="button"
                data-press
                onClick={() => onSubmit({ query: prompt.value })}
              >
                <Sparkles size={17} aria-hidden="true" />
                <span>{prompt.label || prompt.value}</span>
                <ArrowUpRight size={16} aria-hidden="true" />
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
