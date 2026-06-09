import { useMemo, useState } from "react";
import { Row, Col } from "antd";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Card,
  Form,
  Input,
  Select,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { dataSourceApi } from "../../../../api/modules/dataSource";
import type {
  DataSourceConnectionConfig,
  DataSourceType,
} from "../../../../api/types/dataSource";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import {
  DATA_CONNECTION_TYPE_META,
  DEFAULT_PORTS,
  FORM_DATA_SOURCE_TYPES,
} from "../types";
import styles from "./index.module.less";

interface AddFormValues {
  type: DataSourceType;
  host?: string;
  port?: number | string;
  user?: string;
  password?: string;
  db?: string;
  filePath?: string;
}

function toPayload(values: AddFormValues) {
  const port =
    values.port === undefined || values.port === null || values.port === ""
      ? undefined
      : Number(values.port);
  const config: DataSourceConnectionConfig = {
    host: values.host?.trim(),
    port: Number.isFinite(port) ? port : undefined,
    user: values.user?.trim(),
    password: values.password,
    db: values.db?.trim(),
    filePath: values.filePath?.trim(),
  };
  return { type: values.type, config };
}

function resolveErrorMessage(t: (key: string) => string, code: string): string {
  const key = `dataConnection.errors.${code}`;
  const translated = t(key);
  return translated === key ? code : translated;
}

function AddDataSourcePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { message } = useAppMessage();
  const [form] = Form.useForm<AddFormValues>();
  const [testing, setTesting] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const selectedType = Form.useWatch("type", form) ?? "mysql";

  const typeOptions = useMemo(
    () =>
      FORM_DATA_SOURCE_TYPES.map((type) => ({
        value: type,
        label: t(DATA_CONNECTION_TYPE_META[type].labelKey),
      })),
    [t],
  );

  const handleTypeChange = (type: DataSourceType) => {
    const port = DEFAULT_PORTS[type];
    if (port) {
      form.setFieldValue("port", port);
    }
  };

  const handleTest = async () => {
    try {
      const values = await form.validateFields();
      setTesting(true);
      const result = await dataSourceApi.testConnection(toPayload(values));
      if (result.success) {
        message.success(
          t("dataConnection.testSuccess", {
            latency: result.latencyMs ?? 0,
          }),
        );
      } else {
        message.error(resolveErrorMessage(t, result.message));
      }
    } catch {
      /* validation */
    } finally {
      setTesting(false);
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      await dataSourceApi.create(toPayload(values));
      message.success(t("dataConnection.addSuccess"));
      navigate("/datapaw/data-connection");
    } catch (error) {
      const code =
        error instanceof Error ? error.message : "createFailed";
      message.error(resolveErrorMessage(t, code));
    } finally {
      setSubmitting(false);
    }
  };

  const isCsv = selectedType === "csv";

  return (
    <div className={styles.addPage}>
      <PageHeader
        items={[
          { title: t("dataConnection.title") },
          { title: t("dataConnection.addBreadcrumb") },
        ]}
      />

      <Card className={styles.formCard}>
        <h2 className={styles.formTitle}>{t("dataConnection.addModalTitle")}</h2>

        <Form
          form={form}
          layout="vertical"
          initialValues={{ type: "mysql", port: DEFAULT_PORTS.mysql }}
          onValuesChange={(changed) => {
            if ("type" in changed && changed.type) {
              handleTypeChange(changed.type as DataSourceType);
            }
          }}
        >
          <Form.Item
            name="type"
            label={t("dataConnection.type")}
            rules={[
              { required: true, message: t("dataConnection.typeRequired") },
            ]}
          >
            <Select
              options={typeOptions}
              placeholder={t("dataConnection.typePlaceholder")}
            />
          </Form.Item>

          {isCsv ? (
            <Form.Item
              name="filePath"
              label={t("dataConnection.filePath")}
              rules={[
                {
                  required: true,
                  message: t("dataConnection.filePathRequired"),
                },
              ]}
            >
              <Input placeholder={t("dataConnection.filePathPlaceholder")} />
            </Form.Item>
          ) : (
            <>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    name="host"
                    label={t("dataConnection.host")}
                    rules={[
                      {
                        required: true,
                        message: t("dataConnection.hostRequired"),
                      },
                    ]}
                  >
                    <Input placeholder={t("dataConnection.hostPlaceholder")} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="port"
                    label={t("dataConnection.port")}
                    rules={[
                      {
                        required: true,
                        message: t("dataConnection.portRequired"),
                      },
                    ]}
                  >
                    <Input
                      type="number"
                      placeholder={t("dataConnection.portPlaceholder")}
                    />
                  </Form.Item>
                </Col>
              </Row>

              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    name="user"
                    label={t("dataConnection.user")}
                    rules={[
                      {
                        required: true,
                        message: t("dataConnection.userRequired"),
                      },
                    ]}
                  >
                    <Input placeholder={t("dataConnection.userPlaceholder")} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="password"
                    label={t("dataConnection.password")}
                  >
                    <Input.Password
                      placeholder={t("dataConnection.passwordPlaceholder")}
                    />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item
                name="db"
                label={t("dataConnection.db")}
                rules={[
                  { required: true, message: t("dataConnection.dbRequired") },
                ]}
              >
                <Input placeholder={t("dataConnection.dbPlaceholder")} />
              </Form.Item>
            </>
          )}

          <div className={styles.actions}>
            <Button loading={testing} onClick={() => void handleTest()}>
              {t("dataConnection.testConnection")}
            </Button>
            <Button
              type="primary"
              loading={submitting}
              onClick={() => void handleSubmit()}
            >
              {t("common.confirm")}
            </Button>
            <Button onClick={() => navigate("/datapaw/data-connection")}>
              {t("common.cancel")}
            </Button>
          </div>
        </Form>
      </Card>
    </div>
  );
}

export default AddDataSourcePage;
