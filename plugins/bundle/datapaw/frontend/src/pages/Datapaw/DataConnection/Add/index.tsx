import { useMemo, useState } from "react";
import { Row, Col } from "antd";
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
  DataSourceCreatePayload,
  DataSourceType,
} from "../../../../api/types/dataSource";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import {
  DATA_CONNECTION_TYPE_META,
  DEFAULT_PORTS,
  FORM_DATA_SOURCE_TYPES,
} from "../types";
import styles from "./index.module.less";

function getDataConnectionRouteBase(): string {
  return window.location.pathname.startsWith("/plugin/datapaw/")
    ? "/plugin/datapaw/datapaw/data-connection"
    : "/datapaw/data-connection";
}

function navigateInHost(path: string): void {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

interface AddFormValues {
  type: DataSourceType;
  name: string;
  host?: string;
  port?: number | string;
  user?: string;
  password?: string;
  db?: string;
  endpoint?: string;
  project_name?: string;
  access_id?: string;
  access_key?: string;
  app_name?: string;
}

function toPayload(values: AddFormValues): DataSourceCreatePayload {
  const name = values.name.trim();
  if (values.type === "odps") {
    const config: DataSourceConnectionConfig = {
      endpoint: values.endpoint?.trim(),
      project_name: values.project_name?.trim(),
      access_id: values.access_id?.trim(),
      access_key: values.access_key,
      app_name: values.app_name?.trim(),
    };
    return { type: values.type, name, config };
  }

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
  };
  return { type: values.type, name, config };
}

function resolveApiErrorCode(error: unknown): string {
  if (error instanceof Error) {
    const idx = error.message.indexOf(" - ");
    return idx === -1 ? error.message : error.message.slice(0, idx);
  }
  return "createFailed";
}

function resolveErrorMessage(t: (key: string) => string, code: string): string {
  const key = `dataConnection.errors.${code}`;
  const translated = t(key);
  return translated === key ? code : translated;
}

function AddDataSourcePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [form] = Form.useForm<AddFormValues>();
  const [testing, setTesting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const routeBase = getDataConnectionRouteBase();

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
      const payload = toPayload(values);
      const result = await dataSourceApi.testConnection({
        type: payload.type,
        config: payload.config,
      });
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
      navigateInHost(routeBase);
    } catch (error) {
      message.error(resolveErrorMessage(t, resolveApiErrorCode(error)));
    } finally {
      setSubmitting(false);
    }
  };

  const isOdps = selectedType === "odps";

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

          <Form.Item
            name="name"
            label={t("dataConnection.name")}
            rules={[
              { required: true, message: t("dataConnection.nameRequired") },
            ]}
          >
            <Input placeholder={t("dataConnection.namePlaceholder")} />
          </Form.Item>

          {isOdps ? (
            <>
              <Form.Item
                name="endpoint"
                label={t("dataConnection.endpoint")}
                rules={[
                  {
                    required: true,
                    message: t("dataConnection.endpointRequired"),
                  },
                ]}
              >
                <Input placeholder={t("dataConnection.endpointPlaceholder")} />
              </Form.Item>

              <Form.Item
                name="project_name"
                label={t("dataConnection.projectName")}
                rules={[
                  {
                    required: true,
                    message: t("dataConnection.projectNameRequired"),
                  },
                ]}
              >
                <Input placeholder={t("dataConnection.projectNamePlaceholder")} />
              </Form.Item>

              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    name="access_id"
                    label={t("dataConnection.accessId")}
                    rules={[
                      {
                        required: true,
                        message: t("dataConnection.accessIdRequired"),
                      },
                    ]}
                  >
                    <Input placeholder={t("dataConnection.accessIdPlaceholder")} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="access_key"
                    label={t("dataConnection.accessKey")}
                    rules={[
                      {
                        required: true,
                        message: t("dataConnection.accessKeyRequired"),
                      },
                    ]}
                  >
                    <Input.Password
                      placeholder={t("dataConnection.accessKeyPlaceholder")}
                    />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item
                name="app_name"
                label={t("dataConnection.appName")}
                rules={[
                  {
                    required: true,
                    message: t("dataConnection.appNameRequired"),
                  },
                ]}
              >
                <Input placeholder={t("dataConnection.appNamePlaceholder")} />
              </Form.Item>
            </>
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
                    rules={[
                      {
                        required: true,
                        message: t("dataConnection.passwordRequired"),
                      },
                    ]}
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
            <Button onClick={() => navigateInHost(routeBase)}>
              {t("common.cancel")}
            </Button>
          </div>
        </Form>
      </Card>
    </div>
  );
}

export default AddDataSourcePage;
