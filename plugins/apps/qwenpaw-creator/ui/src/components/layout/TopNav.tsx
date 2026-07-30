import { LeftOutlined } from "@ant-design/icons";
import { Tooltip } from "antd";
import { CircleHelp, Images, LayoutList } from "lucide-react";
import { Link, useParams, usePathname, useRouter } from "@/routing/navigation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useOnboardingStore } from "@/store/onboardingStore";
import Breadcrumb from "./Breadcrumb";
import ModelBadges from "@/components/creator/ModelBadges";
import logoMarkUrl from "@/assets/design/logo-mark.png";

const MAIN_TABS = [
  { key: "plan", label: "视频方案", icon: LayoutList },
  { key: "assets", label: "资产库", icon: Images },
] as const;

function activeTabKey(routeSection: string): string {
  return routeSection === "assets" ? "assets" : "plan";
}

export default function TopNav() {
  const { id = "" } = useParams();
  const pathname = usePathname();
  const router = useRouter();
  const project = useProjectSnapshotStore((state) => state.project);
  const requestProjectTour = useOnboardingStore(
    (state) => state.requestProjectTour,
  );
  const requestAssetsTour = useOnboardingStore(
    (state) => state.requestAssetsTour,
  );

  if (!project) return null;
  const routeSection = pathname.split("/").filter(Boolean)[2] || "plan";
  const activeKey = activeTabKey(routeSection);
  const replayTour = () => {
    // Launch the tour matching the current page; the workspace tour's anchors
    // live on the video plan page.
    if (activeKey === "assets") {
      requestAssetsTour();
      return;
    }
    if (activeKey !== "plan") router.push(`/project/${id}/plan`);
    requestProjectTour();
  };
  const masterScript = project.description || "";
  const masterScriptPreview =
    masterScript.length > 20 ? `${masterScript.slice(0, 20)}…` : masterScript;

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
            <span className="block max-w-[180px] shrink-0 truncate text-[13px] font-semibold leading-tight text-[var(--color-text-primary)] md:max-w-[240px]">
              {project.name}
            </span>
            <Tooltip title={masterScript} placement="right">
              <span className="block min-w-0 max-w-[180px] truncate text-[11px] font-normal leading-tight text-[var(--color-text-secondary)] md:max-w-[240px]">
                原始脚本：{masterScriptPreview}
              </span>
            </Tooltip>
          </div>
          <Breadcrumb />
        </div>
      </div>

      <nav className="flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-1">
        {MAIN_TABS.map((tab) => {
          const isActive = tab.key === activeKey;
          const Icon = tab.icon;
          return (
            <Link
              key={tab.key}
              href={`/project/${id}/${tab.key}`}
              data-onboarding-id={
                tab.key === "assets" ? "assets-tab" : undefined
              }
              className={`inline-flex h-[31px] items-center gap-1.5 rounded-full px-3 text-xs font-bold transition-colors md:px-4 ${
                isActive
                  ? "bg-[var(--color-accent-soft)] text-[var(--color-text-primary)] shadow-[inset_0_0_0_1px_rgba(255,127,22,0.18)]"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {tab.label}
            </Link>
          );
        })}
      </nav>

      <div className="flex min-w-0 items-center justify-end gap-2">
        <Tooltip title="重新查看新手引导">
          <button
            type="button"
            onClick={replayTour}
            className="icon-button shrink-0"
            aria-label="重新查看新手引导"
          >
            <CircleHelp className="h-3.5 w-3.5" />
          </button>
        </Tooltip>
        <ModelBadges />
      </div>
    </header>
  );
}
