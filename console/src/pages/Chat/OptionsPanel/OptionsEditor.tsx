import React from "react";
import { Form, Input, ColorPicker, Flex, Divider, InputNumber } from "antd";
import { createStyles } from "antd-style";
import { Button, IconButton, Switch } from "@agentscope-ai/design";
import { SparkDeleteLine, SparkPlusLine } from "@agentscope-ai/icons";
import FormItem from "./FormItem";
import getDefaultConfig from "./defaultConfig";

const useStyles = createStyles(({ token }) => ({
  container: {
    height: "100%",
    display: "flex",
    flexDirection: "column",
  },

  form: {
    height: 0,
    flex: 1,
    padding: "8px 16px 16px 16px",
    overflow: "auto",
  },
  actions: {
    padding: 16,
    display: "flex",
    borderTop: `1px solid ${token.colorBorderSecondary}`,
    justifyContent: "flex-end",
    gap: 16,
  },
}));

interface OptionsEditorProps {
  value?: Record<string, unknown>;
  onChange?: (value: Record<string, unknown>) => void;
}

const OptionsEditor: React.FC<OptionsEditorProps> = ({ value, onChange }) => {
  const { styles } = useStyles();
  const [form] = Form.useForm();

  const handleSave = () => {
    form
      .validateFields()
      .then((values) => {
        const defaults = getDefaultConfig();
        onChange?.({
          ...values,
          _customized: {
            disclaimer:
              values.sender?.disclaimer !== defaults.sender.disclaimer,
            greeting: values.welcome?.greeting !== defaults.welcome.greeting,
            description:
              values.welcome?.description !== defaults.welcome.description,
            prompts:
              JSON.stringify(values.welcome?.prompts) !==
              JSON.stringify(defaults.welcome.prompts),
          },
        });
      })
      .catch((error) => {
        console.error("Validation failed:", error);
      });
  };

  const handleReset = () => {
    form.setFieldsValue(getDefaultConfig());
  };

  return (
    <div className={styles.container}>
      <Form
        className={styles.form}
        form={form}
        layout="vertical"
        initialValues={value}
      >
        <Divider orientation="left">Theme</Divider>

        <FormItem
          name={["theme", "colorPrimary"]}
          label="colorPrimary"
          normalize={(value) => value.toHexString()}
        >
          <ColorPicker />
        </FormItem>

        <FormItem
          name={["theme", "colorBgBase"]}
          label="colorBgBase"
          normalize={(value) => value.toHexString()}
        >
          <ColorPicker />
        </FormItem>

        <FormItem
          name={["theme", "colorTextBase"]}
          label="colorTextBase"
          normalize={(value) => value.toHexString()}
        >
          <ColorPicker />
        </FormItem>

        <FormItem name={["theme", "darkMode"]} label="darkMode">
          <Switch />
        </FormItem>

        <FormItem
          name={["theme", "leftHeader", "logo"]}
          label="leftHeader.logo"
        >
          <Input />
        </FormItem>

        <FormItem
          name={["theme", "leftHeader", "title"]}
          label="leftHeader.title"
        >
          <Input />
        </FormItem>

        <Divider orientation="left">Sender</Divider>

        <FormItem name={["sender", "disclaimer"]} label="disclaimer">
          <Input />
        </FormItem>

        <FormItem name={["sender", "maxLength"]} label="maxLength">
          <InputNumber min={1000} />
        </FormItem>

        <Divider orientation="left">Welcome</Divider>

        <FormItem name={["welcome", "greeting"]} label="greeting">
          <Input />
        </FormItem>

        <FormItem name={["welcome", "description"]} label="description">
          <Input />
        </FormItem>

        <FormItem name={["welcome", "avatar"]} label="avatar">
          <Input />
        </FormItem>

        <FormItem name={["welcome", "prompts"]} isList label="prompts">
          {(
            fields: { key: string; name: string }[],
            {
              add,
              remove,
            }: { add: (item: any) => void; remove: (name: string) => void },
          ) => {
            return (
              <div>
                {fields.map((field) => {
                  return (
                    <Flex key={field.key} gap={6}>
                      <Form.Item
                        style={{ flex: 1 }}
                        key={field.key}
                        name={[field.name, "value"]}
                      >
                        <Input />
                      </Form.Item>
                      <IconButton
                        icon={<SparkPlusLine />}
                        onClick={() => add({})}
                      ></IconButton>
                      <IconButton
                        icon={<SparkDeleteLine />}
                        onClick={() => remove(field.name)}
                      ></IconButton>
                    </Flex>
                  );
                })}
              </div>
            );
          }}
        </FormItem>

        <Divider orientation="left">API</Divider>

        <FormItem name={["api", "baseURL"]} label="baseURL">
          <Input />
        </FormItem>

        <FormItem name={["api", "token"]} label="token">
          <Input />
        </FormItem>
      </Form>

      <div className={styles.actions}>
        <Button onClick={handleReset}>Reset</Button>
        <Button type="primary" onClick={handleSave}>
          Save & Copy
        </Button>
      </div>
    </div>
  );
};

export default OptionsEditor;
