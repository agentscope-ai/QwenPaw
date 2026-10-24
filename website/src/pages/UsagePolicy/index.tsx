import ReactMarkdown from "react-markdown";
import policy from "./usage-policy.md?raw";

export default function UsagePolicy() {
  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-10 sm:py-14">
      <article className="docs-content" lang="en">
        <ReactMarkdown>{policy}</ReactMarkdown>
      </article>
    </main>
  );
}
