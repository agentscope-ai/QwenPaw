import { usePathname } from "@/routing/navigation";
import { useOnboardingStore } from "@/store/onboardingStore";
import { useTranslation } from "react-i18next";
import TourRunner, { type TourStepBlueprint } from "./TourRunner";
import { MockAssetCards } from "./TourMocks";

/**
 * Asset library tour: auto-triggered on first visit to the assets page.
 * Emphasizes that visual settings the Agent generates (characters/scenes etc.,
 * e.g. in short-drama scenarios) accumulate here.
 */

export default function AssetsTour() {
  const { t } = useTranslation();
  const pathname = usePathname();
  const tourDone = useOnboardingStore((state) => state.assetsTourDone);
  const tourRequested = useOnboardingStore(
    (state) => state.assetsTourRequested,
  );
  const completeTour = useOnboardingStore((state) => state.completeAssetsTour);

  const STEPS: TourStepBlueprint[] = [
    {
      selectors: ['[data-onboarding-id="assets-grid"]'],
      title: t("onboarding.assetsTourTitle"),
      description: (
        <div className="space-y-2">
          <p>{t("onboarding.assetsTourDesc")}</p>
          <MockAssetCards />
        </div>
      ),
    },
    {
      selectors: ['[data-onboarding-id="assets-filters"]'],
      title: t("onboarding.assetsTourFilter"),
      description: t("onboarding.assetsTourFilterDesc"),
    },
    {
      selectors: ['[data-onboarding-id="assets-upload"]'],
      title: t("onboarding.assetsTourUpload"),
      description: t("onboarding.assetsTourUploadDesc"),
    },
    {
      selectors: ['[data-onboarding-id="assets-detail"]'],
      title: t("onboarding.assetsTourDetail"),
      description: t("onboarding.assetsTourDetailDesc"),
    },
  ];

  const onAssetsPage = pathname.includes("/assets");
  return (
    <TourRunner
      steps={STEPS}
      shouldRun={onAssetsPage && (tourRequested || !tourDone)}
      onFinish={completeTour}
    />
  );
}
