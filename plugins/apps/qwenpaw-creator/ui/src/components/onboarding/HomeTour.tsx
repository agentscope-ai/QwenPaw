import { useOnboardingStore } from "@/store/onboardingStore";
import TourRunner, { type TourStepBlueprint } from "./TourRunner";
import ModelSetupGuide from "./ModelSetupGuide";

/**
 * Home page tour: auto-triggered the first time the project list page opens.
 * Model configuration is a prerequisite for entering the creation workspace,
 * so it is covered in the very first step on the home page.
 */

const STEPS: TourStepBlueprint[] = [
  {
    selectors: [
      '[data-onboarding-id="model-config"]',
      '[data-onboarding-id="model-badges"]',
    ],
    title: "第一步：配置模型",
    description: (
      <div>
        <p className="mb-2 text-xs leading-5 text-[var(--color-text-secondary)]">
          点击这里打开模型配置；顶栏徽标会实时显示 LLM、VLM、Grounding、
          ASR、图片与视频生成模型的启用状态。开始创作前需要先完成所需模型的配置：
        </p>
        <ModelSetupGuide />
      </div>
    ),
  },
  {
    selectors: ['[data-onboarding-id="create-project"]'],
    title: "第二步：开始创作",
    description:
      "选择视频场景（短剧 / 剪辑 / 通用），用一句话描述你的创意，也可以添加文件、文件夹或粘贴链接导入素材。当前场景的必选模型未配置时，这里会给出提示并可直达配置。",
  },
  {
    selectors: [
      '[data-onboarding-id="projects-tab"]',
      '[data-onboarding-id="project-list"]',
    ],
    title: "第三步：进入创作工作区",
    description:
      "项目创建后会出现在「我的项目」中，点击项目卡片即可进入创作工作区：Agent 会规划创作总纲与时间轴并生成画面。首次进入工作区还有一段专属导览。",
  },
];

export default function HomeTour() {
  const tourDone = useOnboardingStore((state) => state.homeTourDone);
  const tourRequested = useOnboardingStore((state) => state.homeTourRequested);
  const completeTour = useOnboardingStore((state) => state.completeHomeTour);

  return (
    <TourRunner
      steps={STEPS}
      shouldRun={tourRequested || !tourDone}
      onFinish={completeTour}
    />
  );
}
