/** Inspiration example cards; hidden until curated content ships. */

export const SHOW_INSPIRATION_EXAMPLES = false;

export interface InspirationExample {
  title: string;
  description: string;
  prompt: string;
}

const EXAMPLES: InspirationExample[] = [
  {
    title: "产品宣传视频",
    description: "创建一个吹风机产品的宣传视频，重点介绍一下产品卖点…",
    prompt:
      "创建一个吹风机产品的宣传视频，重点介绍一下产品卖点，时长控制在30秒左右。",
  },
  {
    title: "短剧制作",
    description: "制作一部末世生存题材的短剧，重点介绍一下主角团…",
    prompt: "制作一部末世生存题材的短剧，重点刻画主角团在废土中的求生与羁绊。",
  },
];

export default function InspirationExamples({
  onPick,
}: {
  onPick?: (example: InspirationExample) => void;
}) {
  if (!SHOW_INSPIRATION_EXAMPLES) return null;
  return (
    <div className="w-full">
      <p className="mb-2 text-sm text-[#808080]">灵感示例</p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {EXAMPLES.map((example) => (
          <button
            key={example.title}
            type="button"
            onClick={() => onPick?.(example)}
            className="cursor-pointer rounded-lg border border-[#eae9e7] bg-white/90 px-4 py-3.5 text-left backdrop-blur-sm transition-colors hover:border-[var(--color-accent)]"
          >
            <p className="text-sm font-medium text-[#474a52]">
              {example.title}
            </p>
            <p className="mt-1.5 truncate text-xs text-[#808080]">
              {example.description}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
