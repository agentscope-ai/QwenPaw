import { Modal, type ModalFuncProps } from "antd";
import { useOverlayContainer } from "./osWindowContainer";

/** Keep hook-based Ant Design dialogs inside the current OS window. */
export function useOsModal() {
  const container = useOverlayContainer();
  const [modal, holder] = Modal.useModal();
  const withContainer = (config: ModalFuncProps): ModalFuncProps => ({
    getContainer: container,
    ...config,
  });

  return {
    holder,
    confirm: (config: ModalFuncProps) => modal.confirm(withContainer(config)),
    info: (config: ModalFuncProps) => modal.info(withContainer(config)),
    success: (config: ModalFuncProps) => modal.success(withContainer(config)),
    warning: (config: ModalFuncProps) => modal.warning(withContainer(config)),
    error: (config: ModalFuncProps) => modal.error(withContainer(config)),
  };
}
