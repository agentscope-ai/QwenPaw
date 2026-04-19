/**
 * Global stub for @agentscope-ai/icons in tests.
 * The real index.js does `import "./src/index.css"` which Node/vitest cannot handle.
 * All icons return a simple <span> stub so tests can find them via data-icon attribute.
 */
import React from 'react'

const makeIcon = (name: string) =>
  function MockIcon(props: Record<string, unknown>) {
    return React.createElement('span', { 'data-icon': name, ...props })
  }

// Export every icon used across the console source files
export const SparkDownLine = makeIcon('SparkDownLine')
export const SparkUpLine = makeIcon('SparkUpLine')
export const SparkCopyLine = makeIcon('SparkCopyLine')
export const SparkAttachmentLine = makeIcon('SparkAttachmentLine')
export const SparkNewChatFill = makeIcon('SparkNewChatFill')
export const SparkHistoryLine = makeIcon('SparkHistoryLine')
export const SparkOperateRightLine = makeIcon('SparkOperateRightLine')
export const SparkEditLine = makeIcon('SparkEditLine')
export const SparkDeleteLine = makeIcon('SparkDeleteLine')
export const SparkMarkLine = makeIcon('SparkMarkLine')
export const SparkMarkFill = makeIcon('SparkMarkFill')
export const SparkSearchLine = makeIcon('SparkSearchLine')
export const SparkPlusLine = makeIcon('SparkPlusLine')
// Language switcher icons
export const SparkChinese02Line = makeIcon('SparkChinese02Line')
export const SparkEnglish02Line = makeIcon('SparkEnglish02Line')
export const SparkJapanLine = makeIcon('SparkJapanLine')
export const SparkRusLine = makeIcon('SparkRusLine')
// Theme toggle icons
export const SparkMoonLine = makeIcon('SparkMoonLine')
export const SparkSunLine = makeIcon('SparkSunLine')
export const SparkComputerLine = makeIcon('SparkComputerLine')
