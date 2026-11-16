import {
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
} from "@agentscope-ai/design";
import type { ToolConfigField } from "../api/modules/tools";

/** The shared config_fields renderer used by core and plugin settings. */
export function ConfigFields({ fields }: { fields: ToolConfigField[] }) {
  return fields.map((field) => {
    const renderInput = () => {
      switch (field.type) {
        case "password":
          return (
            <Input.Password
              placeholder={field.placeholder}
              autoComplete="off"
            />
          );
        case "number":
          return (
            <InputNumber
              placeholder={field.placeholder}
              min={field.min}
              max={field.max}
              style={{ width: "100%" }}
            />
          );
        case "boolean":
          return <Switch />;
        case "select":
          return (
            <Select placeholder={field.placeholder}>
              {field.options?.map((option) => (
                <Select.Option key={option} value={option}>
                  {option}
                </Select.Option>
              ))}
            </Select>
          );
        case "textarea":
          return (
            <Input.TextArea
              placeholder={field.placeholder}
              rows={4}
              autoSize={{ minRows: 2, maxRows: 8 }}
            />
          );
        default:
          return <Input placeholder={field.placeholder} />;
      }
    };
    return (
      <Form.Item
        key={field.name}
        name={field.name}
        label={field.label}
        rules={[
          { required: field.required, message: `${field.label} is required` },
        ]}
        help={field.help}
        valuePropName={field.type === "boolean" ? "checked" : "value"}
      >
        {renderInput()}
      </Form.Item>
    );
  });
}
