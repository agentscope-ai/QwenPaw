import { Alert, Spin } from "antd";
import { Button, Modal } from "@agentscope-ai/design";
import { RefreshCw, ShieldCheck, Smartphone } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { buildAuthHeaders } from "../api/authHeaders";
import { getApiUrl } from "../api/config";

interface PairingResponse {
  pairing_uri: string;
  qrcode_img: string;
  expires_at: number;
}

interface MobilePairingModalProps {
  open: boolean;
  onClose: () => void;
}

export function MobilePairingModal({ open, onClose }: MobilePairingModalProps) {
  const [pairing, setPairing] = useState<PairingResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [remaining, setRemaining] = useState(0);

  const createPairing = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(getApiUrl("/auth/pairing"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...buildAuthHeaders(),
        },
        body: JSON.stringify({ base_url: window.location.origin }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Could not create a pairing code.");
      }
      setPairing((await response.json()) as PairingResponse);
    } catch (caught) {
      setPairing(null);
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not create a pairing code.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void createPairing();
    if (!open) {
      setPairing(null);
      setError("");
    }
  }, [createPairing, open]);

  useEffect(() => {
    if (!pairing) return;
    const update = () => {
      setRemaining(
        Math.max(0, pairing.expires_at - Math.floor(Date.now() / 1000)),
      );
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [pairing]);

  return (
    <Modal
      centered
      footer={null}
      onCancel={onClose}
      open={open}
      title={null}
      width={420}
    >
      <div style={{ padding: "18px 10px 10px", textAlign: "center" }}>
        <div
          style={{
            width: 52,
            height: 52,
            margin: "0 auto 16px",
            borderRadius: 17,
            background: "#E3EAE2",
            color: "#506554",
            display: "grid",
            placeItems: "center",
          }}
        >
          <Smartphone size={24} />
        </div>
        <h2 style={{ margin: 0, color: "#171A18", fontSize: 24 }}>
          Pair QwenPaw Mobile
        </h2>
        <p
          style={{ margin: "10px auto 20px", maxWidth: 320, color: "#70756F" }}
        >
          Scan with the QwenPaw app. This one-time code expires after two
          minutes and never contains your password.
        </p>

        <div
          style={{
            minHeight: 260,
            display: "grid",
            placeItems: "center",
            border: "1px solid #E2DED6",
            borderRadius: 20,
            background: "#FAF8F4",
          }}
        >
          {loading ? <Spin /> : null}
          {!loading && pairing && remaining > 0 ? (
            <img
              alt="QwenPaw mobile pairing QR code"
              src={`data:image/png;base64,${pairing.qrcode_img}`}
              style={{ width: 224, height: 224 }}
            />
          ) : null}
          {!loading && pairing && remaining === 0 ? (
            <Button icon={<RefreshCw size={16} />} onClick={createPairing}>
              Create a new code
            </Button>
          ) : null}
        </div>

        {error ? (
          <Alert
            message={error}
            showIcon
            style={{ marginTop: 16 }}
            type="error"
          />
        ) : null}
        {pairing && remaining > 0 ? (
          <div
            style={{
              marginTop: 16,
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              gap: 7,
              color: "#627066",
              fontSize: 13,
            }}
          >
            <ShieldCheck size={15} />
            Expires in {remaining}s
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
