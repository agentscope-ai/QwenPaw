import { useState, useEffect } from "react";
import { message, Modal } from "@agentscope-ai/design";
import api from "../../../api";
import type { SkillSpec } from "../../../api/types";

export function useSkills() {
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);

  const fetchSkills = async () => {
    setLoading(true);
    try {
      const data = await api.listSkills();
      if (data) {
        setSkills(data);
      }
    } catch (error) {
      console.error("Failed to load skills", error);
      message.error("Failed to load skills");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;

    const loadSkills = async () => {
      await fetchSkills();
    };

    if (mounted) {
      loadSkills();
    }

    return () => {
      mounted = false;
    };
  }, []);

  const createSkill = async (name: string, content: string) => {
    try {
      await api.createSkill(name, content);
      message.success("Created successfully");
      await fetchSkills();
      return true;
    } catch (error) {
      console.error("Failed to save skill", error);
      message.error("Failed to save");
      return false;
    }
  };

  const importFromHub = async (input: string) => {
    const text = (input || "").trim();
    if (!text) {
      message.warning("Please provide a hub skill URL");
      return false;
    }
    if (!text.startsWith("http://") && !text.startsWith("https://")) {
      message.warning(
        "Please enter a valid URL starting with http:// or https://",
      );
      return false;
    }
    try {
      setImporting(true);
      const payload = { bundle_url: text, enable: true, overwrite: false };
      const result = await api.installHubSkill(payload);
      if (result?.installed) {
        message.success(`Imported skill: ${result.name}`);
        await fetchSkills();
        return true;
      }
      message.error("Import failed");
      return false;
    } catch (error) {
      console.error("Failed to import skill from hub", error);
      message.error("Import failed");
      return false;
    } finally {
      setImporting(false);
    }
  };

  const toggleEnabled = async (skill: SkillSpec) => {
    try {
      if (skill.enabled) {
        await api.disableSkill(skill.name);
        setSkills((prev) =>
          prev.map((s) =>
            s.name === skill.name ? { ...s, enabled: false } : s,
          ),
        );
        message.success("Disabled successfully");
      } else {
        await api.enableSkill(skill.name);
        setSkills((prev) =>
          prev.map((s) =>
            s.name === skill.name ? { ...s, enabled: true } : s,
          ),
        );
        message.success("Enabled successfully");
      }
      return true;
    } catch (error) {
      console.error("Failed to toggle skill", error);
      message.error("Operation failed");
      return false;
    }
  };

  const deleteSkill = async (skill: SkillSpec) => {
    const confirmed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: "Confirm Delete",
        content: `Are you sure you want to delete skill "${skill.name}"? This action cannot be undone.`,
        okText: "Delete",
        okType: "danger",
        cancelText: "Cancel",
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });

    if (!confirmed) return false;

    try {
      const result = await api.deleteSkill(skill.name);
      if (result.deleted) {
        message.success("Deleted successfully");
        await fetchSkills();
        return true;
      } else {
        message.error("Failed to delete skill");
        return false;
      }
    } catch (error) {
      console.error("Failed to delete skill", error);
      message.error("Failed to delete skill");
      return false;
    }
  };

  return {
    skills,
    loading,
    importing,
    createSkill,
    importFromHub,
    toggleEnabled,
    deleteSkill,
  };
}
