import type { ComponentProps } from "@ant-design/x-markdown";
import { RenderableCodeBlock } from "./RenderableCodeBlock";

export { RenderableCodeBlock };

export const renderableCodeComponents: Record<
  string,
  React.ComponentType<ComponentProps>
> = {
  code: RenderableCodeBlock,
};
