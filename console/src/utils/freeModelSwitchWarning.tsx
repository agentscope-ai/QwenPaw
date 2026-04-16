import { Checkbox, Modal } from "@agentscope-ai/design";
import type { TFunction } from "i18next";

const FREE_MODEL_WARNING_DISABLED_KEY =
  "copaw_free_model_switch_warning_disabled";

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

export async function confirmFreeModelSwitch({
  provider,
  model,
  t,
}: ConfirmFreeModelSwitchOptions): Promise<boolean> {
  if (!model.is_free || isWarningDisabled()) {
    return true;
  }

  const providerWebsite = getProviderWebsite(provider);
  let dontShowAgain = false;

  return new Promise<boolean>((resolve) => {
    let settled = false;

    const settle = (value: boolean) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };

    Modal.confirm({
      title: t("models.freeModelWarningTitle"),
      content: (
        <div>
          <div>{t("models.freeModelWarningMessage")}</div>
                 <div className="qwenpaw-free-model-warning-link-row">
            <a href={providerWebsite} target="_blank" rel="noreferrer">
              {providerWebsite}
            </a>
          </div>
          <div className="qwenpaw-free-model-warning-checkbox-row">
            <Checkbox
              onChange={(event) => {
                dontShowAgain = Boolean(event?.target?.checked);
              }}
            >
              {t("models.freeModelWarningDontShowAgain")}
            </Checkbox>
          </div>
        </div>
      ),
      okText: t("common.confirm"),
      cancelText: t("common.cancel"),
      onOk: () => {
        if (dontShowAgain) {
          disableWarning();
        }
        settle(true);
      },
      onCancel: () => settle(false),
      afterClose: () => settle(false),
    });
  });
}
