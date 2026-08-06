import { usePathname } from "@/routing/navigation";
import { useOnboardingStore } from "@/store/onboardingStore";
import TourRunner, { type TourStepBlueprint } from "./TourRunner";
import {
  LiveDockToggleDemo,
  LiveSelectionDemo,
  MockAgentChat,
  MockElementDetail,
  MockTimeline,
} from "./TourMocks";

/**
 * Project workspace tour: auto-triggered on first visit to the video plan page.
 * Model-configuration guidance already happened up front in the home page
 * HomeTour, so this one focuses on the creation workspace itself.
 */

const STEPS: TourStepBlueprint[] = [
  {
    selectors: ['[data-onboarding-id="creative-brief"]'],
    title: "创作总纲",
    description:
      "Agent 对整个视频的规划：创作方向与总纲在这里，点击标题可以展开查看完整内容。",
  },
  {
    selectors: ["[data-timeline-panel]"],
    title: "时间轴",
    description: (
      <div className="space-y-2">
        <p>
          画面、剪辑、字幕动效与声音在时间轴上叠加呈现。新建项目时 Agent
          正在规划，轨道内容会随规划与生成结果实时出现。
        </p>
        <MockTimeline />
      </div>
    ),
  },
  {
    selectors: ['[data-onboarding-id="element-detail"]'],
    title: "内容详情",
    description: (
      <div className="space-y-2">
        <p>
          Agent 规划出分镜等内容后，从左侧列表或时间轴点击任意一项，
          在这里查看并直接编辑它的字段。
        </p>
        <MockElementDetail />
      </div>
    ),
  },
  {
    selectors: ["[data-timeline-panel]"],
    title: "选中即上下文",
    description: (
      <div className="space-y-2">
        <p>
          在页面任意位置划选文字，或在时间轴上点击选中时间点、拖拽框选时间段，
          都会浮出「添加到对话」按钮，把选中内容作为上下文发给创作助手。
        </p>
        <LiveSelectionDemo />
      </div>
    ),
  },
  {
    selectors: ["[data-agent-dock]", "[data-agent-dock-handle]"],
    title: "创作助手（AgentDock）",
    description: (
      <div className="space-y-2">
        <p>
          随时输入修改意图，@ 可引用分镜、素材等对象；Agent
          修改的审阅与高消费生成确认也在这里完成。
        </p>
        <MockAgentChat />
        <LiveDockToggleDemo />
      </div>
    ),
  },
  {
    selectors: ["[data-download-render]"],
    title: "成片下载与项目导出",
    description:
      "时间轴上的内容全部就绪后会自动合成成片；合成进度显示在按钮上。点开菜单可下载成片视频，也可将整个项目导出为归档。",
  },
  {
    selectors: ['[data-onboarding-id="assets-tab"]'],
    title: "资产库",
    description:
      "生成的分镜图、视频片段与你上传的素材都沉淀在资产库中，可以随时查看、复用并在对话里引用。",
  },
];

export default function ProjectTour() {
  const pathname = usePathname();
  const tourDone = useOnboardingStore((state) => state.projectTourDone);
  const tourRequested = useOnboardingStore(
    (state) => state.projectTourRequested,
  );
  const completeTour = useOnboardingStore((state) => state.completeProjectTour);

  const onPlanPage = pathname.includes("/plan");
  return (
    <TourRunner
      steps={STEPS}
      shouldRun={onPlanPage && (tourRequested || !tourDone)}
      onFinish={completeTour}
    />
  );
}
