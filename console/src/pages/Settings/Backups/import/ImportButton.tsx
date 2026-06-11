/**
 * Wraps a hidden <input type="file"> and an "Import" button into one component.
 * The parent only needs to handle the picked File object via onPick.
 */
import { useRef } from "react";
import { Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

interface Props {
  onPick: (file: File) => void;
}

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
      <Button variant="outline" onClick={() => fileInputRef.current?.click()}>
        <Upload className="mr-2 h-4 w-4" />
        {t("backup.import")}
      </Button>
    </>
  );
}
