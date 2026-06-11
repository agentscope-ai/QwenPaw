const STYLE_ID = "datapaw-task-graph-panel-style";

const CSS = `
[data-datapaw-task-graph-card] {
  width: 100%;
}
.datapaw-task-card-sender-prefix {
  flex-shrink: 0;
  width: 100%;
}
.datapaw-task-plan {
  margin-top: 8px;
  margin-bottom: 8px;
  background: var(--colorBgContainer, #fff);
  border-radius: 8px;
  border: 1px solid var(--colorBorder, #e8e8e8);
  overflow: hidden;
}
html.dark-mode .datapaw-task-plan {
  background: #1f1f1f;
  border-color: rgba(255, 255, 255, 0.12);
}
.datapaw-task-plan-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px 12px;
  font-size: 15px;
  font-weight: 600;
  line-height: 22px;
  color: rgba(0, 0, 0, 0.88);
  border-bottom: 1px solid #f0f0f0;
}
.datapaw-task-plan-title-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
html.dark-mode .datapaw-task-plan-title {
  color: rgba(255, 255, 255, 0.88);
  border-bottom-color: rgba(255, 255, 255, 0.08);
}
.datapaw-task-plan .datapaw-task-table .ant-table,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table {
  background: transparent;
}
.datapaw-task-plan .datapaw-task-table .ant-table-container,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-container {
  border: none !important;
  border-radius: 0;
}
.datapaw-task-plan .datapaw-task-table .ant-table-content table,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-content table {
  table-layout: fixed;
}
.datapaw-task-plan .datapaw-task-table .ant-table-body,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-body {
  max-height: 240px !important;
  overflow-y: auto !important;
}
.datapaw-task-plan .datapaw-task-table .ant-table-thead > tr > th,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-thead > tr > th {
  background: #fafafa !important;
  border-bottom: none !important;
  font-size: 14px;
  font-weight: 600;
  color: rgba(0, 0, 0, 0.88);
  padding: 8px 12px !important;
}
.datapaw-task-plan .datapaw-task-table .ant-table-thead > tr > th::before,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-thead > tr > th::before {
  display: none;
}
.datapaw-task-plan .datapaw-task-table .ant-table-thead > tr > th:first-child,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-thead > tr > th:first-child {
  padding-left: 20px !important;
}
.datapaw-task-plan .datapaw-task-table .ant-table-tbody > tr > td,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-tbody > tr > td {
  padding: 9px 12px !important;
  font-size: 14px;
  line-height: 20px;
  color: rgba(0, 0, 0, 0.88);
  border-bottom: 1px solid #f0f0f0;
  background: #fff;
}
.datapaw-task-plan .datapaw-task-table .ant-table-tbody > tr > td:first-child,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-tbody > tr > td:first-child {
  padding-left: 20px !important;
}
.datapaw-task-plan .datapaw-task-table .ant-table-thead > tr > th:last-child,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-thead > tr > th:last-child,
.datapaw-task-plan .datapaw-task-table .ant-table-tbody > tr > td:last-child,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-tbody > tr > td:last-child {
  padding-right: 0 !important;
}
.datapaw-task-plan .datapaw-task-table .ant-table-tbody > tr:last-child > td,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-tbody > tr:last-child > td {
  border-bottom: none;
}
.datapaw-task-plan .datapaw-task-table .ant-table-tbody > tr:hover > td,
.datapaw-task-plan .datapaw-task-table .qwenpaw-table-tbody > tr:hover > td {
  background: #fff;
}
html.dark-mode .datapaw-task-plan .datapaw-task-table .ant-table-thead > tr > th,
html.dark-mode .datapaw-task-plan .datapaw-task-table .qwenpaw-table-thead > tr > th {
  background: rgba(255, 255, 255, 0.04) !important;
  color: rgba(255, 255, 255, 0.88);
}
html.dark-mode .datapaw-task-plan .datapaw-task-table .ant-table-tbody > tr > td,
html.dark-mode .datapaw-task-plan .datapaw-task-table .qwenpaw-table-tbody > tr > td {
  color: rgba(255, 255, 255, 0.88);
  border-bottom-color: rgba(255, 255, 255, 0.08);
  background: #1f1f1f;
}
.datapaw-task-plan .datapaw-status-header,
.datapaw-task-plan .datapaw-status-cell {
  text-align: center !important;
}
.datapaw-task-plan .datapaw-task-content {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.datapaw-task-plan .datapaw-clickable-row {
  cursor: pointer;
}
.datapaw-task-plan .datapaw-clickable-row:hover td {
  background: rgba(22, 119, 255, 0.04) !important;
}
html.dark-mode .datapaw-task-plan .datapaw-clickable-row:hover td {
  background: rgba(22, 119, 255, 0.08) !important;
}
.datapaw-task-plan .datapaw-status-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  padding: 0 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 400;
  white-space: nowrap;
  line-height: 18px;
}
.datapaw-task-plan .datapaw-status-tag.statusDone {
  background: #f6ffed;
  color: #389e0d;
}
.datapaw-task-plan .datapaw-status-tag.statusInProgress {
  background: #e6f4ff;
  color: #1677ff;
}
.datapaw-task-plan .datapaw-status-tag.statusPending,
.datapaw-task-plan .datapaw-status-tag.statusNotStarted {
  background: #f5f5f5;
  color: rgba(0, 0, 0, 0.65);
}
.datapaw-task-plan .datapaw-status-tag.statusFailed {
  background: #fff2f0;
  color: #cf1322;
}
.datapaw-task-plan .datapaw-status-tag.statusStale {
  background: #fff7e6;
  color: #d46b08;
}
.datapaw-task-plan .datapaw-status-tag.statusAbandoned {
  background: #f5f5f5;
  color: rgba(0, 0, 0, 0.65);
}
html.dark-mode .datapaw-task-plan .datapaw-status-tag.statusDone {
  background: rgba(82, 196, 26, 0.16);
  color: #95de64;
}
html.dark-mode .datapaw-task-plan .datapaw-status-tag.statusInProgress {
  background: rgba(22, 119, 255, 0.16);
  color: #69b1ff;
}
html.dark-mode .datapaw-task-plan .datapaw-status-tag.statusPending,
html.dark-mode .datapaw-task-plan .datapaw-status-tag.statusNotStarted,
html.dark-mode .datapaw-task-plan .datapaw-status-tag.statusAbandoned {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.65);
}
html.dark-mode .datapaw-task-plan .datapaw-status-tag.statusFailed {
  background: rgba(255, 77, 79, 0.16);
  color: #ff7875;
}
html.dark-mode .datapaw-task-plan .datapaw-status-tag.statusStale {
  background: rgba(250, 173, 20, 0.16);
  color: #ffc069;
}
.datapaw-header-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  flex: 0 0 auto;
}
.datapaw-correction-btn {
  height: 32px;
  padding-inline: 12px;
  font-size: 14px;
  border-radius: 8px;
  color: #1677ff !important;
  border-color: #1677ff !important;
  background: transparent !important;
  box-shadow: none !important;
}
.datapaw-correction-btn:hover {
  color: #4096ff !important;
  border-color: #4096ff !important;
  background: rgba(22, 119, 255, 0.04) !important;
}
.datapaw-artifact-btn {
  height: 32px;
  padding-inline: 12px;
  font-size: 14px;
  border-radius: 8px;
  color: rgba(0, 0, 0, 0.88) !important;
  border-color: #d9d9d9 !important;
  background: #fff !important;
  box-shadow: none !important;
}
.datapaw-artifact-btn:hover {
  color: #1677ff !important;
  border-color: #1677ff !important;
}
html.dark-mode .datapaw-artifact-btn {
  color: rgba(255, 255, 255, 0.88) !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
  background: transparent !important;
}
.datapaw-artifact-drawer .ant-drawer-body,
.datapaw-artifact-drawer .qwenpaw-drawer-body {
  padding: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
}
.datapaw-artifact-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
  font-size: 16px;
  font-weight: 600;
  color: rgba(0, 0, 0, 0.88);
}
html.dark-mode .datapaw-artifact-drawer-header {
  border-bottom-color: rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.88);
}
.datapaw-artifact-drawer-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(0, 0, 0, 0.45);
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
}
.datapaw-artifact-drawer-close:hover {
  background: rgba(0, 0, 0, 0.04);
  color: rgba(0, 0, 0, 0.88);
}
.datapaw-artifact-drawer-body {
  flex: 1;
  overflow: auto;
}
.datapaw-artifact-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.datapaw-artifact-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  border-bottom: 1px solid #f5f5f5;
}
html.dark-mode .datapaw-artifact-row {
  border-bottom-color: rgba(255, 255, 255, 0.08);
}
.datapaw-artifact-path {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: rgba(0, 0, 0, 0.88);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
html.dark-mode .datapaw-artifact-path {
  color: rgba(255, 255, 255, 0.88);
}
.datapaw-artifact-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #1677ff;
}
.datapaw-artifact-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.datapaw-artifact-action-btn {
  min-width: 52px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: #fff;
  font-size: 12px;
  color: rgba(0, 0, 0, 0.88);
  cursor: pointer;
}
.datapaw-artifact-action-btn:hover {
  border-color: #1677ff;
  color: #1677ff;
}
html.dark-mode .datapaw-artifact-action-btn {
  background: #1f1f1f;
  border-color: rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.88);
}
.datapaw-artifact-drawer-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  padding: 24px;
  color: rgba(0, 0, 0, 0.45);
  font-size: 14px;
}
.datapaw-actions-header {
  text-align: right !important;
  padding-right: 16px !important;
}
.datapaw-plan-correction-trigger {
  display: inline-flex;
  vertical-align: middle;
}
.datapaw-plan-correction-popover .ant-popover-inner,
.datapaw-plan-correction-popover .qwenpaw-popover-inner {
  padding: 0 !important;
  border: 1px solid #ebebeb;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  overflow: visible;
}
html.dark-mode .datapaw-plan-correction-popover .ant-popover-inner,
html.dark-mode .datapaw-plan-correction-popover .qwenpaw-popover-inner {
  border-color: rgba(255, 255, 255, 0.12);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.36);
}
.datapaw-plan-correction-panel {
  width: 480px;
  padding: 20px;
}
.datapaw-plan-correction-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.datapaw-plan-correction-title {
  font-size: 16px;
  font-weight: 600;
  color: rgba(0, 0, 0, 0.88);
  line-height: 24px;
}
html.dark-mode .datapaw-plan-correction-title {
  color: rgba(255, 255, 255, 0.88);
}
.datapaw-plan-correction-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  background: transparent;
  color: rgba(0, 0, 0, 0.45);
  font-size: 12px;
  cursor: pointer;
}
.datapaw-plan-correction-close:hover {
  color: rgba(0, 0, 0, 0.88);
}
html.dark-mode .datapaw-plan-correction-close {
  color: rgba(255, 255, 255, 0.45);
}
html.dark-mode .datapaw-plan-correction-close:hover {
  color: rgba(255, 255, 255, 0.88);
}
.datapaw-plan-correction-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.datapaw-plan-correction-cancel {
  min-width: 72px;
  height: 32px;
  border-radius: 6px;
}
.datapaw-plan-correction-confirm {
  min-width: 88px;
  height: 32px;
  border-radius: 6px;
}
.datapaw-yaml-editor {
  display: flex;
  height: 336px;
  border: 1px solid #ebebeb;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}
html.dark-mode .datapaw-yaml-editor {
  border-color: rgba(255, 255, 255, 0.12);
  background: #141414;
}
.datapaw-yaml-line-numbers {
  flex-shrink: 0;
  width: 36px;
  padding: 12px 0 12px 4px;
  background: #fff;
  overflow: hidden;
  user-select: none;
}
html.dark-mode .datapaw-yaml-line-numbers {
  background: #141414;
}
.datapaw-yaml-line-number {
  height: 20px;
  padding-right: 6px;
  color: rgba(0, 0, 0, 0.25);
  font-family: 'SF Mono', SFMono-Regular, ui-monospace, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 20px;
  text-align: right;
}
html.dark-mode .datapaw-yaml-line-number {
  color: rgba(255, 255, 255, 0.25);
}
.datapaw-yaml-code-area {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 100%;
  overflow: hidden;
}
.datapaw-yaml-highlight,
.datapaw-yaml-textarea {
  margin: 0;
  padding: 12px 12px 12px 0;
  border: none;
  outline: none;
  resize: none;
  width: 100%;
  height: 100%;
  font-family: 'SF Mono', SFMono-Regular, ui-monospace, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 20px;
  white-space: pre;
  overflow: auto;
  tab-size: 2;
}
.datapaw-yaml-highlight {
  position: absolute;
  inset: 0;
  pointer-events: none;
  color: rgba(0, 0, 0, 0.88);
  background: transparent;
}
html.dark-mode .datapaw-yaml-highlight {
  color: rgba(255, 255, 255, 0.88);
}
.datapaw-yaml-textarea {
  position: relative;
  z-index: 1;
  color: transparent;
  caret-color: rgba(0, 0, 0, 0.88);
  background: transparent;
}
html.dark-mode .datapaw-yaml-textarea {
  caret-color: rgba(255, 255, 255, 0.88);
}
.datapaw-yaml-code-line {
  min-height: 20px;
}
.datapaw-yaml-key {
  color: #2f54eb;
}
.datapaw-yaml-value {
  color: rgba(0, 0, 0, 0.88);
}
html.dark-mode .datapaw-yaml-value {
  color: rgba(255, 255, 255, 0.88);
}
.datapaw-yaml-punctuation {
  color: rgba(0, 0, 0, 0.88);
}
html.dark-mode .datapaw-yaml-punctuation {
  color: rgba(255, 255, 255, 0.88);
}
`;

export function injectTaskGraphStyles(): void {
  if (typeof document === "undefined") return;
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.appendChild(style);
}
