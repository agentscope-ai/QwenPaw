import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Loader2 } from "lucide-react";
import { useTheme } from "../../../../contexts/ThemeContext";
import { useChannelQrcode, type ChannelQrcodeConfig } from "./useChannelQrcode";

interface QrcodeAuthBlockProps extends ChannelQrcodeConfig {
  label: string;
  buttonText: string;
  imageAlt: string;
  hintText: string;
}

export function QrcodeAuthBlock({
  label,
  buttonText,
  imageAlt,
  hintText,
  ...qrcodeConfig
}: QrcodeAuthBlockProps) {
  const { isDark } = useTheme();
  const qrcode = useChannelQrcode(qrcodeConfig);

  return (
    <div className="flex flex-col gap-1.5 mb-4">
      <Label>{label}</Label>
      <Button
        type="button"
        className="w-full"
        disabled={qrcode.loading}
        onClick={qrcode.fetchQrcode}
      >
        {qrcode.loading && <Loader2 size={14} className="animate-spin mr-2" />}
        {buttonText}
      </Button>
      {qrcode.loading && (
        <div className="flex justify-center mt-3">
          <Loader2 className="animate-spin text-muted-foreground" size={24} />
        </div>
      )}
      {qrcode.qrcodeImg && !qrcode.loading && (
        <div className="flex flex-col items-center mt-3 gap-2">
          <img
            src={`data:image/png;base64,${qrcode.qrcodeImg}`}
            alt={imageAlt}
            className="w-[200px] h-[200px]"
          />
          <p
            className={`text-xs ${isDark ? "text-white/45" : "text-black/45"}`}
          >
            {hintText}
          </p>
        </div>
      )}
    </div>
  );
}
