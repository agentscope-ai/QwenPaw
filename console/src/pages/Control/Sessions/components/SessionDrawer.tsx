import { useTranslation } from "react-i18next";
import type { Session } from "./constants";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetFooter,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2 } from "lucide-react";

interface SessionFormState {
  name: string;
}

interface SessionDrawerProps {
  open: boolean;
  editingSession: Session | null;
  formValues: SessionFormState;
  saving: boolean;
  onClose: () => void;
  onFormChange: (values: Partial<SessionFormState>) => void;
  onSubmit: () => void;
}

export function SessionDrawer({
  open,
  editingSession,
  formValues,
  saving,
  onClose,
  onFormChange,
  onSubmit,
}: SessionDrawerProps) {
  const { t } = useTranslation();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit();
  };

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-[520px] flex flex-col p-0">
        <SheetHeader className="px-6 py-4 border-b">
          <SheetTitle>{t("sessions.editSession")}</SheetTitle>
        </SheetHeader>

        <form
          onSubmit={handleSubmit}
          className="flex-1 overflow-y-auto px-6 py-4"
        >
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="session-name">name</Label>
              <Input
                id="session-name"
                placeholder="Session name"
                value={formValues.name}
                onChange={(e) => onFormChange({ name: e.target.value })}
              />
            </div>

            {editingSession && (
              <>
                <div className="flex flex-col gap-1.5">
                  <Label>id</Label>
                  <Input value={editingSession.id} disabled />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>session_id</Label>
                  <Input value={editingSession.session_id} disabled />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>user_id</Label>
                  <Input value={editingSession.user_id} disabled />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>channel</Label>
                  <Input value={editingSession.channel} disabled />
                </div>
              </>
            )}
          </div>
        </form>

        <SheetFooter className="px-6 py-4 border-t flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={onSubmit} disabled={saving}>
            {saving && <Loader2 size={14} className="animate-spin mr-2" />}
            {t("common.save")}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
