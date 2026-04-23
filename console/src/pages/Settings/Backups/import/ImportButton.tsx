/**
 * Wraps a hidden <input type="file"> and an "Import" button into one component.
 * The parent only needs to handle the picked File object via onPick — it never
 * has to manage a ref or wire up onChange directly.
 */
import { useRef } from "react";
import { Button } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

interface Props {
  onPick: (file: File) => void;
}

/**
 * Wraps the hidden file input + trigger button so the parent
 * doesn't need to manage a ref or wire up onChange directly.
 */
export default function ImportButton({ onPick }: Props) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".zip"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            onPick(file);
            e.target.value = "";
          }
        }}
      />
      <Button
        icon={<UploadOutlined />}
        onClick={() => fileInputRef.current?.click()}
      >
        {t("backup.import")}
      </Button>
    </>
  );
}
