import { useOnboardingStore } from "@/store/onboardingStore";
import { useTranslation } from "react-i18next";
import TourRunner, { type TourStepBlueprint } from "./TourRunner";
import ModelSetupGuide from "./ModelSetupGuide";

/**
 * Home page tour: auto-triggered the first time the project list page opens.
 * Model configuration is a prerequisite for entering the creation workspace,
 * so it is covered in the very first step on the home page.
 */

export default function HomeTour() {
  const { t } = useTranslation();
  const tourDone = useOnboardingStore((state) => state.homeTourDone);
  const tourRequested = useOnboardingStore((state) => state.homeTourRequested);
  const completeTour = useOnboardingStore((state) => state.completeHomeTour);

  const STEPS: TourStepBlueprint[] = [
    {
      selectors: [
        '[data-onboarding-id="model-config"]',
        '[data-onboarding-id="model-badges"]',
      ],
      title: t("onboarding.step1Title"),
      description: (
        <div>
          <p className="mb-2 text-xs leading-5 text-[var(--color-text-secondary)]">
            {t("onboarding.step1Desc")}
          </p>
          <ModelSetupGuide />
        </div>
      ),
    },
    {
      selectors: ['[data-onboarding-id="create-project"]'],
      title: t("onboarding.step2Title"),
      description: t("onboarding.step2Desc"),
    },
    {
      selectors: [
        '[data-onboarding-id="projects-tab"]',
        '[data-onboarding-id="project-list"]',
      ],
      title: t("onboarding.step3Title"),
      description: t("onboarding.step3Desc"),
    },
  ];

  return (
    <TourRunner
      steps={STEPS}
      shouldRun={tourRequested || !tourDone}
      onFinish={completeTour}
    />
  );
}
