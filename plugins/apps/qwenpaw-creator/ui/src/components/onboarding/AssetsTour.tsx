import { usePathname } from "@/routing/navigation";
import { useOnboardingStore } from "@/store/onboardingStore";
import TourRunner, { type TourStepBlueprint } from "./TourRunner";
import { MockAssetCards } from "./TourMocks";

/**
 * Asset library tour: auto-triggered on first visit to the assets page.
 * Emphasizes that visual settings the Agent generates (characters/scenes etc.,
 * e.g. in short-drama scenarios) accumulate here.
 */

const STEPS: TourStepBlueprint[] = [
  {
    selectors: ['[data-onboarding-id="assets-grid"]'],
    title: "项目资产总览",
    description: (
      <div className="space-y-2">
        <p>
          项目里的所有素材都汇集在这里：你上传的「来源」素材、Agent
          生成的「产物」（分镜图、视频片段、成片），以及短剧等场景下的「角色 /
          场景 / 道具」视觉设定——比如主角的定妆锚点图，Agent
          生成分镜时会引用它们保持形象一致。
        </p>
        <MockAssetCards />
      </div>
    ),
  },
  {
    selectors: ['[data-onboarding-id="assets-filters"]'],
    title: "按类型筛选",
    description:
      "按来源素材、生成产物、视觉设定筛选，也可以只看图片 / 视频 / 音频，或用右侧搜索框按名称查找。",
  },
  {
    selectors: ['[data-onboarding-id="assets-upload"]'],
    title: "随时补充素材",
    description:
      "上传文件，或添加链接 / 文本素材；入库后会出现在列表中，Agent 与时间轴内容都能引用它们。",
  },
  {
    selectors: ['[data-onboarding-id="assets-detail"]'],
    title: "资产详情",
    description:
      "点击任意卡片，在这里查看它的版本、引用关系与产物状态；需要检查或完善某项资产时，可在创作助手对话中 @ 引用它。",
  },
];

export default function AssetsTour() {
  const pathname = usePathname();
  const tourDone = useOnboardingStore((state) => state.assetsTourDone);
  const tourRequested = useOnboardingStore(
    (state) => state.assetsTourRequested,
  );
  const completeTour = useOnboardingStore((state) => state.completeAssetsTour);

  const onAssetsPage = pathname.includes("/assets");
  return (
    <TourRunner
      steps={STEPS}
      shouldRun={onAssetsPage && (tourRequested || !tourDone)}
      onFinish={completeTour}
    />
  );
}
