import { useLayoutEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useChatAnywhereInput } from "@agentscope-ai/chat";

const CHAT_LAYOUT_CLASS_SUFFIX = "-chat-anywhere-layout";
const SENDER_ACTION_CLASS_SUFFIX = "-sender-actions-btn";
const SENDER_PREFIX_CLASS_SUFFIX = "-sender-prefix";
const SENDER_ACTIONS_CLASS_SUFFIX = "-sender-actions-list";
const RECORDING_ICON_CLASS_SUFFIX = "-sender-actions-btn-recording-icon";
const COMPOSER_SUBMIT_ATTRIBUTE = "data-qwenpaw-composer-submit";

function hasClassToken(element: Element, suffix: string): boolean {
  return Array.from(element.classList).some((token) => token.endsWith(suffix));
}

function findAncestorByClassToken(
  element: Element,
  suffix: string,
): HTMLElement | null {
  let current = element.parentElement;
  while (current) {
    if (hasClassToken(current, suffix)) return current;
    current = current.parentElement;
  }
  return null;
}

function isWithinComposerAction(node: Node, layout: HTMLElement): boolean {
  if (!(node instanceof Element)) return false;
  let current: Element | null = node;
  while (current && current !== layout) {
    if (hasClassToken(current, SENDER_ACTION_CLASS_SUFFIX)) return true;
    current = current.parentElement;
  }
  return false;
}

function containsComposerAction(node: Node): boolean {
  if (!(node instanceof Element)) return false;
  if (hasClassToken(node, SENDER_ACTION_CLASS_SUFFIX)) return true;
  return Array.from(node.querySelectorAll("button")).some((button) =>
    hasClassToken(button, SENDER_ACTION_CLASS_SUFFIX),
  );
}

function mutationTouchesComposer(
  records: MutationRecord[],
  layout: HTMLElement,
): boolean {
  return records.some(
    (record) =>
      isWithinComposerAction(record.target, layout) ||
      Array.from(record.addedNodes).some(containsComposerAction),
  );
}

function labelSdkComposerActions(
  layout: HTMLElement,
  labels: {
    microphone: string;
    stopMicrophone: string;
    send: string;
    stop: string;
  },
  loading: boolean,
) {
  const actionButtons = Array.from(
    layout.querySelectorAll<HTMLButtonElement>("button"),
  ).filter((button) => hasClassToken(button, SENDER_ACTION_CLASS_SUFFIX));

  for (const button of actionButtons) {
    if (findAncestorByClassToken(button, SENDER_PREFIX_CLASS_SUFFIX)) {
      button.removeAttribute(COMPOSER_SUBMIT_ATTRIBUTE);
      const recording = Array.from(button.querySelectorAll("*")).some(
        (element) => hasClassToken(element, RECORDING_ICON_CLASS_SUFFIX),
      );
      button.setAttribute(
        "aria-label",
        recording ? labels.stopMicrophone : labels.microphone,
      );
      continue;
    }

    if (findAncestorByClassToken(button, SENDER_ACTIONS_CLASS_SUFFIX)) {
      button.setAttribute(COMPOSER_SUBMIT_ATTRIBUTE, "true");
      button.setAttribute("aria-label", loading ? labels.stop : labels.send);
    }
  }
}

export default function ComposerAccessibilityLabels() {
  const { t } = useTranslation();
  const markerRef = useRef<HTMLSpanElement>(null);
  const loading = useChatAnywhereInput((value) => value.loading);

  useLayoutEffect(() => {
    const marker = markerRef.current;
    if (!marker) return;
    const layout = findAncestorByClassToken(marker, CHAT_LAYOUT_CLASS_SUFFIX);
    if (!layout) return;

    const labels = {
      microphone: t("chat.speech.startRecording"),
      stopMicrophone: t("chat.speech.stopRecording"),
      send: t("chat.composer.send"),
      stop: t("chat.composer.stop"),
    };
    const applyLabels = () =>
      labelSdkComposerActions(layout, labels, Boolean(loading));

    applyLabels();
    const observer = new MutationObserver((records) => {
      if (mutationTouchesComposer(records, layout)) applyLabels();
    });
    observer.observe(layout, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [loading, t]);

  return <span ref={markerRef} hidden />;
}
