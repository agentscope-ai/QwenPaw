import { usePathname } from "@/routing/navigation";
import { useOnboardingStore } from "@/store/onboardingStore";
import { useTranslation } from "react-i18next";
import TourRunner, { type TourStepBlueprint } from "./TourRunner";
import {
  LiveDockToggleDemo,
  LiveSelectionDemo,
  MockAgentChat,
  MockElementDetail,
  MockSnapshotPanel,
  MockTimeline,
} from "./TourMocks";

/**
 * Project workspace tour: auto-triggered on first visit to the video plan page.
 * Model-configuration guidance already happened up front in the home page
 * HomeTour, so this one focuses on the creation workspace itself.
 */

export default function ProjectTour() {
  const { t } = useTranslation();
  const pathname = usePathname();
  const tourDone = useOnboardingStore((state) => state.projectTourDone);
  const tourRequested = useOnboardingStore(
    (state) => state.projectTourRequested,
  );
  const completeTour = useOnboardingStore((state) => state.completeProjectTour);

  const STEPS: TourStepBlueprint[] = [
    {
      // The creative brief moved to the blueprint page; fall back to the plan
      // header so the tour still anchors its first step on this page.
      selectors: [
        '[data-onboarding-id="creative-brief"]',
        "[data-plan-page] header",
      ],
      title: t("onboarding.projectTourBrief"),
      description: t("onboarding.projectTourBriefDesc"),
    },
    {
      selectors: ["[data-timeline-tracks]", "[data-timeline-panel]"],
      title: t("onboarding.projectTourTimeline"),
      description: (
        <div className="space-y-2">
          <p>{t("onboarding.projectTourTimelineDesc")}</p>
          <MockTimeline />
        </div>
      ),
    },
    {
      selectors: ["[data-snapshot-entry]"],
      title: t("onboarding.projectTourSnapshot"),
      description: (
        <div className="space-y-2">
          <p>{t("onboarding.projectTourSnapshotDesc")}</p>
          <MockSnapshotPanel />
        </div>
      ),
    },
    {
      selectors: [
        '[data-onboarding-id="element-detail"]',
        "[data-element-rail]",
      ],
      title: t("onboarding.projectTourDetail"),
      description: (
        <div className="space-y-2">
          <p>{t("onboarding.projectTourDetailDesc")}</p>
          <MockElementDetail />
        </div>
      ),
    },
    {
      selectors: ["[data-timeline-tracks]", "[data-timeline-panel]"],
      title: t("onboarding.projectTourContext"),
      description: (
        <div className="space-y-2">
          <p>{t("onboarding.projectTourContextDesc")}</p>
          <LiveSelectionDemo />
        </div>
      ),
    },
    {
      selectors: ["[data-agent-dock]", "[data-agent-dock-handle]"],
      title: t("onboarding.projectTourDock"),
      description: (
        <div className="space-y-2">
          <p>{t("onboarding.projectTourDockDesc")}</p>
          <MockAgentChat />
          <LiveDockToggleDemo />
        </div>
      ),
    },
    {
      // Download / export moved to the blueprint page; this step anchors on
      // the compose button and points the user there.
      selectors: ["[data-compose-render]"],
      title: t("onboarding.projectTourDownload"),
      description: t("onboarding.projectTourDownloadDesc"),
    },
    {
      selectors: ['[data-onboarding-id="assets-tab"]'],
      title: t("onboarding.projectTourAssets"),
      description: t("onboarding.projectTourAssetsDesc"),
    },
  ];

  const onPlanPage = pathname.includes("/plan");
  return (
    <TourRunner
      steps={STEPS}
      shouldRun={onPlanPage && (tourRequested || !tourDone)}
      onFinish={completeTour}
    />
  );
}
