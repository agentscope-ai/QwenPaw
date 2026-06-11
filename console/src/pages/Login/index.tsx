import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Lock, User, Loader2 } from "lucide-react";
import { useAppMessage } from "../../hooks/useAppMessage";
import { authApi } from "../../api/modules/auth";
import { setAuthToken } from "../../api/config";
import { useTheme } from "../../contexts/ThemeContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const [hasUsers, setHasUsers] = useState(true);
  const { message } = useAppMessage();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    authApi
      .getStatus()
      .then((res) => {
        if (!res.enabled) {
          navigate("/chat", { replace: true });
          return;
        }
        setHasUsers(res.has_users);
        if (!res.has_users) {
          setIsRegister(true);
        }
      })
      .catch(() => {});
  }, [navigate]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    setLoading(true);
    try {
      const raw = searchParams.get("redirect") || "/chat";
      const redirect =
        raw.startsWith("/") && !raw.startsWith("//") ? raw : "/chat";

      if (isRegister) {
        const res = await authApi.register(username, password);
        if (res.token) {
          setAuthToken(res.token);
          message.success(t("login.registerSuccess"));
          navigate(redirect, { replace: true });
        }
      } else {
        const res = await authApi.login(username, password);
        if (res.token) {
          setAuthToken(res.token);
          navigate(redirect, { replace: true });
        } else {
          message.info(t("login.authNotEnabled"));
          navigate(redirect, { replace: true });
        }
      }
    } catch (err) {
      message.error(
        isRegister
          ? err instanceof Error
            ? err.message
            : t("login.registerFailed")
          : t("login.failed"),
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={cn(
        "h-screen flex items-center justify-center",
        isDark
          ? "[background:linear-gradient(135deg,#0f0c29_0%,#302b63_50%,#24243e_100%)]"
          : "[background:linear-gradient(135deg,#f5f7fa_0%,#c3cfe2_100%)]",
      )}
    >
      <div className="w-[400px] p-8 rounded-xl shadow-2xl bg-card">
        <div className="text-center mb-8">
          <img
            src={isDark ? "/logo-dark.svg" : "/logo-light.svg"}
            alt="QwenPaw"
            className="h-12 mx-auto mb-3"
          />
          <h2 className="m-0 font-semibold text-xl">
            {isRegister ? t("login.registerTitle") : t("login.title")}
          </h2>
          {!hasUsers && (
            <p className="mt-2 mb-0 text-[13px] text-muted-foreground">
              {t("login.firstUserHint")}
            </p>
          )}
        </div>

        <form
          onSubmit={onSubmit}
          className="flex flex-col gap-4"
          autoComplete="off"
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="login-username" className="sr-only">
              {t("login.usernamePlaceholder")}
            </Label>
            <div className="relative">
              <User
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                id="login-username"
                className="pl-9 h-11"
                placeholder={t("login.usernamePlaceholder")}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                required
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="login-password" className="sr-only">
              {t("login.passwordPlaceholder")}
            </Label>
            <div className="relative">
              <Lock
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                id="login-password"
                type="password"
                className="pl-9 h-11"
                placeholder={t("login.passwordPlaceholder")}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <Button
            type="submit"
            className="h-11 rounded-lg font-medium w-full mt-2"
            disabled={loading}
          >
            {loading && <Loader2 size={16} className="animate-spin mr-2" />}
            {isRegister ? t("login.register") : t("login.submit")}
          </Button>
        </form>
      </div>
    </div>
  );
}
