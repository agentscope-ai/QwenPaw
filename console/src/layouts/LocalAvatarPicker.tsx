import { useRef, useState } from "react";
import { message } from "antd";
import { Check, ImagePlus, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { DEFAULT_AVATAR, useLocalAvatar } from "../stores/localAvatarStore";
import { SharedModal } from "../components/interaction/SharedModal";
import menu from "./sidebarSettingsPanel.module.less";
import styles from "./localAvatarPicker.module.less";

export default function LocalAvatarPicker() {
  const { t } = useTranslation();
  const {
    selected,
    history,
    images,
    select,
    upload: uploadAvatar,
    loadHistory,
  } = useLocalAvatar();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const choose = async (value: string | null) => {
    setBusy(true);
    try {
      await select(value);
    } catch {
      message.error(t("sidebar.avatarSaveFailed"));
    } finally {
      setBusy(false);
    }
  };
  const upload = async (file?: File) => {
    if (!file) return;
    if (
      !["image/png", "image/jpeg", "image/webp", "image/gif"].includes(
        file.type,
      ) ||
      file.size > 10 * 1024 * 1024 ||
      (file.type === "image/gif" && file.size > 2 * 1024 * 1024)
    ) {
      message.error(t("sidebar.avatarInvalid"));
      return;
    }
    setBusy(true);
    if (file.type === "image/gif") {
      try {
        await uploadAvatar(file);
      } catch {
        message.error(t("sidebar.avatarSaveFailed"));
      } finally {
        setBusy(false);
      }
      return;
    }
    const url = URL.createObjectURL(file);
    try {
      const picture = new Image();
      picture.src = url;
      await picture.decode();
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 192;
      const side = Math.min(picture.naturalWidth, picture.naturalHeight);
      canvas
        .getContext("2d")!
        .drawImage(
          picture,
          (picture.naturalWidth - side) / 2,
          (picture.naturalHeight - side) / 2,
          side,
          side,
          0,
          0,
          192,
          192,
        );
      const blob = await new Promise<Blob>((resolve, reject) =>
        canvas.toBlob(
          (value) =>
            value ? resolve(value) : reject(new Error("Image encoding failed")),
          "image/webp",
          0.88,
        ),
      );
      await uploadAvatar(blob);
    } catch {
      message.error(t("sidebar.avatarInvalid"));
    } finally {
      URL.revokeObjectURL(url);
      setBusy(false);
    }
  };
  return (
    <>
      <SharedModal
        className={styles.modal}
        styles={{ mask: { background: "rgb(0 0 0 / 16%)" } }}
        open={open}
        onCancel={() => setOpen(false)}
        title={t("sidebar.changeAvatar")}
        footer={null}
        width={360}
        centered
      >
        <div className={styles.panel}>
          <button
            type="button"
            data-press
            className={styles.upload}
            disabled={busy}
            onClick={() => input.current?.click()}
          >
            <Upload size={16} />
            {t(busy ? "common.loading" : "sidebar.uploadAvatar")}
          </button>
          <input
            ref={input}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            hidden
            onChange={(event) => {
              void upload(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <p>{t("sidebar.avatarHistory")}</p>
          <div className={styles.grid}>
            {[null, ...history.map((item) => item.id)].map((value, index) => (
              <button
                key={value ?? "default"}
                type="button"
                data-press
                aria-label={
                  index === 0
                    ? t("sidebar.defaultAvatar")
                    : t("sidebar.historyAvatar", { number: index })
                }
                aria-pressed={selected === value}
                disabled={busy}
                onClick={() => void choose(value)}
              >
                <img src={value ? images[value] : DEFAULT_AVATAR} alt="" />
                {selected === value && <Check size={13} />}
              </button>
            ))}
          </div>
        </div>
      </SharedModal>
      <button
        type="button"
        data-press
        className={menu.menuItem}
        onClick={() => {
          setOpen(true);
          setBusy(true);
          void loadHistory()
            .catch(() => message.error(t("sidebar.avatarLoadFailed")))
            .finally(() => setBusy(false));
        }}
      >
        <ImagePlus size={16} />
        <span>{t("sidebar.changeAvatar")}</span>
      </button>
    </>
  );
}
