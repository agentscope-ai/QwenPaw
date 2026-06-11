import { createRoot } from "react-dom/client";
import { useState } from "react";
import type { TFunction } from "i18next";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

const FREE_MODEL_WARNING_DISABLED_KEY =
  "qwenpaw_free_model_switch_warning_disabled";

const PROVIDER_WEBSITE_SAMPLES: Record<string, string> = {
  openrouter: "https://openrouter.ai/collections/free-models",
  opencode: "https://opencode.ai/docs/zen",
  //   Add more provider website samples here as needed
};

interface FreeModelWarningProvider {
  id: string;
  base_url?: string;
}

interface FreeModelWarningModel {
  is_free?: boolean;
}

interface ConfirmFreeModelSwitchOptions {
  provider: FreeModelWarningProvider;
  model: FreeModelWarningModel;
  t: TFunction;
}

function isWarningDisabled(): boolean {
  return localStorage.getItem(FREE_MODEL_WARNING_DISABLED_KEY) === "1";
}

function disableWarning(): void {
  localStorage.setItem(FREE_MODEL_WARNING_DISABLED_KEY, "1");
}

function getProviderWebsite(provider: FreeModelWarningProvider): string {
  return PROVIDER_WEBSITE_SAMPLES[provider.id] ?? provider.base_url ?? "#";
}

interface DialogProps {
  providerWebsite: string;
  t: TFunction;
  onConfirm: (dontShow: boolean) => void;
  onCancel: () => void;
}

function FreeModelWarningDialog({
  providerWebsite,
  t,
  onConfirm,
  onCancel,
}: DialogProps) {
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const checkboxId = "free-model-dont-show";
  return (
    <AlertDialog open>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t("models.freeModelWarningTitle")}
          </AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div className="flex flex-col gap-3">
              <p>{t("models.freeModelWarningMessage")}</p>
              <a
                href={providerWebsite}
                target="_blank"
                rel="noreferrer"
                className="text-primary underline break-all"
              >
                {providerWebsite}
              </a>
              <div className="flex items-center gap-2">
                <Checkbox
                  id={checkboxId}
                  checked={dontShowAgain}
                  onCheckedChange={(v) => setDontShowAgain(Boolean(v))}
                />
                <Label
                  htmlFor={checkboxId}
                  className="cursor-pointer font-normal"
                >
                  {t("models.freeModelWarningDontShowAgain")}
                </Label>
              </div>
            </div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>
            {t("common.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction onClick={() => onConfirm(dontShowAgain)}>
            {t("common.confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export async function confirmFreeModelSwitch({
  provider,
  model,
  t,
}: ConfirmFreeModelSwitchOptions): Promise<boolean> {
  if (!model.is_free || isWarningDisabled()) {
    return true;
  }

  const providerWebsite = getProviderWebsite(provider);

  return new Promise<boolean>((resolve) => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    const cleanup = () => {
      root.unmount();
      container.remove();
    };

    root.render(
      <FreeModelWarningDialog
        providerWebsite={providerWebsite}
        t={t}
        onConfirm={(dontShow) => {
          if (dontShow) disableWarning();
          cleanup();
          resolve(true);
        }}
        onCancel={() => {
          cleanup();
          resolve(false);
        }}
      />,
    );
  });
}
