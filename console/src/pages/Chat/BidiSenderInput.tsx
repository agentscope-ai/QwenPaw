import { Input } from "antd";
import {
  forwardRef,
  type ComponentProps,
  type ComponentRef,
} from "react";

type TextAreaProps = ComponentProps<typeof Input.TextArea>;
type TextAreaRef = ComponentRef<typeof Input.TextArea>;

/**
 * Thin Sender TextArea wrapper that opts into Unicode BiDi auto-detection.
 * The vendor Sender defaults to LTR; `dir="auto"` lets the browser pick
 * direction from the first strong character (e.g. Arabic vs English).
 */
const BidiSenderInput = forwardRef<TextAreaRef, TextAreaProps>(
  function BidiSenderInput(props, ref) {
    return <Input.TextArea {...props} ref={ref} dir="auto" />;
  },
);

export default BidiSenderInput;
