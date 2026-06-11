import { useFormContext, useWatch, Controller } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ADBPGConfigCard() {
  const { t } = useTranslation();
  const { register, control } = useFormContext();

  const apiMode =
    useWatch({ control, name: "adbpg_memory_config.api_mode" }) ?? "rest";

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("agentConfig.adbpgConfig.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <Label>{t("agentConfig.adbpgConfig.apiMode")}</Label>
          <Controller
            control={control}
            name="adbpg_memory_config.api_mode"
            defaultValue="rest"
            render={({ field }) => (
              <Select
                value={field.value ?? "rest"}
                onValueChange={field.onChange}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="sql">SQL (Direct)</SelectItem>
                  <SelectItem value="rest">REST API</SelectItem>
                </SelectContent>
              </Select>
            )}
          />
        </div>

        {apiMode === "sql" ? (
          <>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.host")}</Label>
              <Input
                placeholder="gp-xxx.gpdb.rds.aliyuncs.com"
                {...register("adbpg_memory_config.host")}
              />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.port")}</Label>
              <Input
                type="number"
                min={1}
                max={65535}
                {...register("adbpg_memory_config.port", {
                  valueAsNumber: true,
                })}
              />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.user")}</Label>
              <Input {...register("adbpg_memory_config.user")} />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.password")}</Label>
              <Input
                type="password"
                {...register("adbpg_memory_config.password")}
              />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.dbname")}</Label>
              <Input {...register("adbpg_memory_config.dbname")} />
            </div>

            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.llmModel")}</Label>
              <Input
                placeholder="qwen-plus"
                {...register("adbpg_memory_config.llm_model")}
              />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.llmApiKey")}</Label>
              <Input
                type="password"
                {...register("adbpg_memory_config.llm_api_key")}
              />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.llmBaseUrl")}</Label>
              <Input
                placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                {...register("adbpg_memory_config.llm_base_url")}
              />
            </div>

            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.embeddingModel")}</Label>
              <Input
                placeholder="text-embedding-v3"
                {...register("adbpg_memory_config.embedding_model")}
              />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.embeddingApiKey")}</Label>
              <Input
                type="password"
                {...register("adbpg_memory_config.embedding_api_key")}
              />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.embeddingBaseUrl")}</Label>
              <Input
                placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                {...register("adbpg_memory_config.embedding_base_url")}
              />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.embeddingDims")}</Label>
              <Input
                type="number"
                min={1}
                max={4096}
                {...register("adbpg_memory_config.embedding_dims", {
                  valueAsNumber: true,
                })}
              />
            </div>
          </>
        ) : (
          <>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.restBaseUrl")}</Label>
              <Input
                placeholder="https://your-adbpg-api.example.com"
                {...register("adbpg_memory_config.rest_base_url")}
              />
            </div>
            <div className="space-y-1">
              <Label>{t("agentConfig.adbpgConfig.restApiKey")}</Label>
              <Input
                type="password"
                {...register("adbpg_memory_config.rest_api_key")}
              />
            </div>
          </>
        )}

        <div className="flex items-center justify-between">
          <Label>{t("agentConfig.adbpgConfig.memoryIsolation")}</Label>
          <Controller
            control={control}
            name="adbpg_memory_config.memory_isolation"
            defaultValue={true}
            render={({ field }) => (
              <Switch
                checked={Boolean(field.value)}
                onCheckedChange={field.onChange}
              />
            )}
          />
        </div>

        <div className="space-y-1">
          <Label>{t("agentConfig.adbpgConfig.searchTimeout")}</Label>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={1}
              max={60}
              {...register("adbpg_memory_config.search_timeout", {
                valueAsNumber: true,
              })}
            />
            <span className="text-sm text-muted-foreground">s</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
