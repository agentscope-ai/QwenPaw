import { LeftOutlined } from "@ant-design/icons";
import { Tooltip } from "antd";
import { CircleHelp, Images, Waypoints } from "lucide-react";
import { Link, navigate } from "@/routing/navigation";
import logoMarkUrl from "@/assets/design/logo-mark.png";
import { DEMO_PROJECT_ID, type ScenarioKey } from "./demoData";

/**
 * Demo variant of the real TopNav: identical shell markup, but the primary
 * pills reflect the redesigned IA — 项目蓝图（结构与创作决策层）与 资产库
 * （全量库存视图）互为平级；时间线编辑是蓝图的下钻层级，不出现在主导航。
 */
export default function DemoTopNav({
  navName,
  navPreview,
  active,
  scenarioKey,
}: {
  navName: string;
  navPreview: string;
  active: "blueprint" | "assets";
  scenarioKey: ScenarioKey;
}) {
  const tabClass = (isActive: boolean) =>
    `inline-flex h-[31px] items-center gap-1.5 rounded-full px-4 text-xs font-bold transition-colors ${
      isActive
        ? "bg-[var(--color-accent-soft)] text-[var(--color-text-primary)] shadow-[inset_0_0_0_1px_rgba(255,127,22,0.18)]"
        : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
    }`;
  return (
    <header className="relative z-[200] grid h-[58px] shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 border-b border-[var(--color-border)] bg-white/88 px-3 backdrop-blur-xl dark:bg-[var(--color-bg-primary)] md:px-4">
      <div className="flex min-w-0 items-center gap-2">
        <Link
          href="/"
          className="icon-button shrink-0"
          aria-label="返回项目列表"
        >
          <LeftOutlined className="text-xs" />
        </Link>
        <img
          src={logoMarkUrl}
          alt=""
          width={34}
          height={34}
          className="hidden shrink-0 sm:block"
        />
        <div className="min-w-0">
          <div className="flex min-w-0 items-baseline gap-1.5">
            <span className="block max-w-[240px] shrink-0 truncate text-[13px] font-semibold leading-tight text-[var(--color-text-primary)]">
              {navName}
            </span>
            <Tooltip title={navPreview} placement="right">
              <span className="block min-w-0 max-w-[280px] truncate text-[11px] font-normal leading-tight text-[var(--color-text-secondary)]">
                {navPreview}
              </span>
            </Tooltip>
          </div>
          <nav className="flex min-w-0 items-center gap-1.5 text-xs text-[var(--color-text-secondary)]">
            <span className="px-1 font-medium text-[var(--color-text-primary)]">
              {active === "assets" ? "资产库" : "项目蓝图"}
            </span>
          </nav>
        </div>
      </div>

      <nav className="flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-1">
        <button
          type="button"
          className={tabClass(active === "blueprint")}
          onClick={() => navigate(`/blueprint-demo?sc=${scenarioKey}`)}
        >
          <Waypoints className="h-3.5 w-3.5" />
          项目蓝图
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent)]" />
        </button>
        <button
          type="button"
          className={tabClass(active === "assets")}
          onClick={() =>
            navigate(
              `/blueprint-demo/${DEMO_PROJECT_ID}/assets?sc=${scenarioKey}`,
            )
          }
        >
          <Images className="h-3.5 w-3.5" />
          资产库
        </button>
      </nav>

      <div className="flex min-w-0 items-center justify-end gap-2">
        <Tooltip title="重新查看新手引导">
          <span className="icon-button shrink-0">
            <CircleHelp className="h-3.5 w-3.5" />
          </span>
        </Tooltip>
        <span className="icon-button shrink-0 text-[11px] font-semibold">
          EN
        </span>
        <span className="inline-flex h-[26px] items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2.5 text-[11px] font-semibold text-[var(--color-text-secondary)]">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
          qwen3-max
        </span>
        <span className="hidden h-[26px] items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2.5 text-[11px] font-semibold text-[var(--color-text-secondary)] lg:inline-flex">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-success)]" />
          wan2.5-t2v
        </span>
      </div>
    </header>
  );
}
