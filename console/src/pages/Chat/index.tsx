import {
  AgentScopeRuntimeWebUI,
  IAgentScopeRuntimeWebUIOptions,
} from "@agentscope-ai/chat";
import { useMemo, useState, useEffect, useRef } from "react";
import { Modal, Button, Result } from "antd";
import { ExclamationCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import sessionApi from "./sessionApi";
import defaultConfig from "./OptionsPanel/defaultConfig";
import Weather from "./Weather";
import { getApiUrl, getApiToken } from "../../api/config";
import { providerApi } from "../../api/modules/provider";
import ModelSelector from "./ModelSelector";
import "./index.module.less";

interface CustomWindow extends Window {
  currentSessionId?: string;
  currentUserId?: string;
  currentChannel?: string;
}

declare const window: CustomWindow;

export default function ChatPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [showModelPrompt, setShowModelPrompt] = useState(false);
  const optionsConfig = defaultConfig;
  const isComposingRef = useRef(false);

  const handleConfigureModel = () => {
    setShowModelPrompt(false);
    navigate("/models");
  };

  const handleSkipConfiguration = () => {
    setShowModelPrompt(false);
  };

  useEffect(() => {
    const handleCompositionStart = () => {
      console.log("[IME] Composition start");
      isComposingRef.current = true;
    };

    const handleCompositionEnd = () => {
      console.log("[IME] Composition end");
      setTimeout(() => {
        isComposingRef.current = false;
        console.log("[IME] Composition state cleared");
      }, 150);
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === "TEXTAREA" && e.key === "Enter") {
        console.log("[IME] KeyDown Enter:", {
          isComposing: (e as any).isComposing,
          isComposingRef: isComposingRef.current,
          shiftKey: e.shiftKey,
        });
      }
    };

    const handleKeyPress = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === "TEXTAREA" && e.key === "Enter" && !e.shiftKey) {
        console.log("[IME] KeyPress Enter:", {
          isComposing: (e as any).isComposing,
          isComposingRef: isComposingRef.current,
        });
        if (isComposingRef.current || (e as any).isComposing) {
          console.log("[IME] Blocking enter key");
          e.stopPropagation();
          e.stopImmediatePropagation();
          return false;
        }
      }
    };

    document.addEventListener("compositionstart", handleCompositionStart, true);
    document.addEventListener("compositionend", handleCompositionEnd, true);
    document.addEventListener("keydown", handleKeyDown, true);
    document.addEventListener("keypress", handleKeyPress, true);

    return () => {
      document.removeEventListener(
        "compositionstart",
        handleCompositionStart,
        true,
      );
      document.removeEventListener(
        "compositionend",
        handleCompositionEnd,
        true,
      );
      document.removeEventListener("keydown", handleKeyDown, true);
      document.removeEventListener("keypress", handleKeyPress, true);
    };
  }, []);

  const options = useMemo(() => {
    const handleBeforeSubmit = async () => {
      if (isComposingRef.current) {
        return false;
      }
      return true;
    };

    const handleModelError = () => {
      setShowModelPrompt(true);
      return new Response(
        JSON.stringify({
          error: "Model not configured",
          message: "Please configure a model first",
        }),
        {
          status: 400,
          headers: { "Content-Type": "application/json" },
        },
      );
    };

    const customFetch = async (data: {
      input: any[];
      biz_params?: any;
      signal?: AbortSignal;
    }): Promise<Response> => {
      try {
        const activeModels = await providerApi.getActiveModels();

        if (
          !activeModels?.active_llm?.provider_id ||
          !activeModels?.active_llm?.model
        ) {
          return handleModelError();
        }
      } catch (error) {
        console.error("Failed to check model configuration:", error);
        return handleModelError();
      }

      const { input, biz_params } = data;

      const lastMessage = input[input.length - 1];
      const session = lastMessage?.session || {};

      const session_id = window.currentSessionId || session?.session_id || "";
      const user_id = window.currentUserId || session?.user_id || "default";
      const channel = window.currentChannel || session?.channel || "console";

      const requestBody = {
        input: input.slice(-1),
        session_id,
        user_id,
        channel,
        stream: true,
        ...biz_params,
      };

      const headers: HeadersInit = {
        "Content-Type": "application/json",
      };

      const token = getApiToken();
      if (token) {
        (headers as Record<string, string>).Authorization = `Bearer ${token}`;
      }

      const url = optionsConfig?.api?.baseURL || getApiUrl("/agent/process");
      const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: data.signal,
      });

      return response;
    };

    return {
      ...optionsConfig,
      sender: {
        ...optionsConfig.sender,
        beforeSubmit: handleBeforeSubmit,
      },
      session: {
        multiple: true,
        api: sessionApi,
      },
      theme: {
        ...optionsConfig.theme,
        rightHeader: <ModelSelector />,
      },
      api: {
        ...optionsConfig.api,
        fetch: customFetch,
        cancel(data: { session_id: string }) {
          console.log(data);
        },
      },
      customToolRenderConfig: {
        "weather search mock": Weather,
      },
    } as unknown as IAgentScopeRuntimeWebUIOptions;
  }, [optionsConfig]);

  return (
    <div style={{ height: "100%", width: "100%" }}>
      <AgentScopeRuntimeWebUI options={options} />

      <Modal open={showModelPrompt} closable={false} footer={null} width={480}>
        <Result
          icon={<ExclamationCircleOutlined style={{ color: "#faad14" }} />}
          title={t("modelConfig.promptTitle")}
          subTitle={t("modelConfig.promptMessage")}
          extra={[
            <Button key="skip" onClick={handleSkipConfiguration}>
              {t("modelConfig.skipButton")}
            </Button>,
            <Button
              key="configure"
              type="primary"
              icon={<SettingOutlined />}
              onClick={handleConfigureModel}
            >
              {t("modelConfig.configureButton")}
            </Button>,
          ]}
        />
      </Modal>
    </div>
  );
}
