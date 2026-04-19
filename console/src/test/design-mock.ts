/**
 * Global stub for @agentscope-ai/design in tests.
 * The real lib/ is 3MB and causes long hangs when loaded via deps.inline.
 * Tests that need specific behavior can override with vi.mock('@agentscope-ai/design', factory).
 */
import React from 'react'

const passThrough = ({ children, ...props }: Record<string, unknown>) =>
  React.createElement('div', props, children as any)

const buttonLike = ({ children, onClick, icon, ...props }: Record<string, unknown>) =>
  React.createElement('button', { onClick, ...props }, icon as any, children as any)

export const IconButton = buttonLike
export const Dropdown = passThrough
export const Button = buttonLike
export const Input = (props: Record<string, unknown>) =>
  React.createElement('input', props as any)

export default { IconButton, Dropdown, Button, Input }
