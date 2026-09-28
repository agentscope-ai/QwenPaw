import { Button, Dropdown } from "@agentscope-ai/design";
import type { MenuProps } from "antd";
import {
  LayoutGrid as AppstoreOutlined,
  Download as DownloadOutlined,
  Import as ImportOutlined,
  Plus as PlusOutlined,
  Upload as UploadOutlined,
} from "lucide-react";
import { useTranslation } from "react-i18next";

interface AddSkillDropdownProps {
  onCreate: () => void;
  /** Skills page only — omitted on the pool page (it IS the pool). */
  onFromPool?: () => void;
  onUploadZip: () => void;
  onFromUrl: () => void;
  onBrowseMarket: () => void;
  uploading?: boolean;
}

/**
 * Single entry point for every way of adding a skill: create, pull from the
 * skill pool, upload a zip, import from a hub URL, or browse the market.
 */
export function AddSkillDropdown({
  onCreate,
  onFromPool,
  onUploadZip,
  onFromUrl,
  onBrowseMarket,
  uploading,
}: AddSkillDropdownProps) {
  const { t } = useTranslation();

  const items: MenuProps["items"] = [
    {
      key: "create",
      label: t("skills.createSkill"),
      icon: <PlusOutlined size="1em" />,
      onClick: onCreate,
    },
    ...(onFromPool
      ? [
          {
            key: "from-pool",
            label: t("skills.downloadFromPool"),
            icon: <DownloadOutlined size="1em" />,
            onClick: onFromPool,
          },
        ]
      : []),
    {
      key: "upload-zip",
      label: t("skills.uploadZip"),
      icon: <UploadOutlined size="1em" />,
      disabled: uploading,
      onClick: onUploadZip,
    },
    {
      key: "from-url",
      label: t("skills.importHub"),
      icon: <ImportOutlined size="1em" />,
      onClick: onFromUrl,
    },
    { type: "divider" },
    {
      key: "market",
      label: t("market.browseMarket"),
      icon: <AppstoreOutlined size="1em" />,
      onClick: onBrowseMarket,
    },
  ];

  return (
    <Dropdown menu={{ items }} placement="bottomRight">
      <Button
        type="primary"
        icon={<PlusOutlined size="1em" />}
        loading={uploading}
      >
        {t("skills.addSkill")}
      </Button>
    </Dropdown>
  );
}
