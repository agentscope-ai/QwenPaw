/**
 * Global stub for @agentscope-ai/design in tests.
 * The real lib/ is 3MB and causes long hangs when loaded via deps.inline.
 * Tests that need specific behavior can override with vi.mock('@agentscope-ai/design', factory).
 */
import React from "react";

const passThrough = ({ children, ...props }: Record<string, unknown>) =>
  React.createElement("div", props, children as any);

const buttonLike = ({
  children,
  onClick,
  icon,
  ...props
}: Record<string, unknown>) =>
  React.createElement(
    "button",
    { onClick, ...props },
    icon as any,
    children as any,
  );

export const IconButton = buttonLike;
export const Dropdown = passThrough;
export const Button = buttonLike;
export const Input = Object.assign(
  (props: Record<string, unknown>) =>
    React.createElement("input", props as any),
  {
    TextArea: (props: Record<string, unknown>) =>
      React.createElement("textarea", props as any),
    Search: (props: Record<string, unknown>) =>
      React.createElement("input", { ...props, type: "search" } as any),
    Password: (props: Record<string, unknown>) =>
      React.createElement("input", { ...props, type: "password" } as any),
    Group: passThrough,
  },
);

export const Switch = ({
  checked,
  onChange,
  ...props
}: Record<string, unknown>) =>
  React.createElement("input", {
    type: "checkbox",
    role: "switch",
    checked,
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      (onChange as ((v: boolean) => void) | undefined)?.(e.target.checked),
    ...props,
  });

export const Modal = Object.assign(passThrough, {
  confirm: () => {},
  info: () => {},
  warning: () => {},
  error: () => {},
});

export const Tag = passThrough;
export const Tooltip = passThrough;
export const Form = Object.assign(passThrough, {
  Item: passThrough,
  useForm: () => [{}],
});
export const InputNumber = (props: Record<string, unknown>) =>
  React.createElement("input", { type: "number", ...props } as any);
export const Spin = passThrough;

export default {
  IconButton,
  Dropdown,
  Button,
  Input,
  Switch,
  Modal,
  Tag,
  Tooltip,
  Form,
  InputNumber,
  Spin,
};
