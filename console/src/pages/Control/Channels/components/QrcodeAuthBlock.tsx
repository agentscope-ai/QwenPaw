import { Button, Form } from "@agentscope-ai/design";
import { Spin } from "antd";
import { useTheme } from "../../../../contexts/ThemeContext";
import { useChannelQrcode, type ChannelQrcodeConfig } from "./useChannelQrcode";

interface QrcodeAuthBlockProps extends ChannelQrcodeConfig {
  /** Form.Item label text */
  label: string;
  /** Button text */
  buttonText: string;
  /** Alt text for the QR code image */
  imageAlt: string;
  /** Hint text shown below the QR code */
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
    <Form.Item label={label}>
      <Button
        type="primary"
        block
        loading={qrcode.loading}
        onClick={qrcode.fetchQrcode}
      >
        {buttonText}
      </Button>
      {qrcode.loading && (
        <div style={{ textAlign: "center", marginTop: 12 }}>
          <Spin />
        </div>
      )}
      {qrcode.qrcodeImg && !qrcode.loading && (
        <div style={{ textAlign: "center", marginTop: 12 }}>
          <img
            src={`data:image/png;base64,${qrcode.qrcodeImg}`}
            alt={imageAlt}
            style={{ width: 200, height: 200 }}
          />
          <div
            style={{
              marginTop: 8,
              fontSize: 12,
              color: isDark ? "rgba(255,255,255,0.45)" : "rgba(0,0,0,0.45)",
            }}
          >
            {hintText}
          </div>
        </div>
      )}
    </Form.Item>
  );
}
