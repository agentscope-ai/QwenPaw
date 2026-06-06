import React from "react";
import { useTranslation } from "react-i18next";
import { CodeOutlined } from "@ant-design/icons";
import type { ToolCardProps, ToolCallContent } from "../types";
import styles from "./ShellExecutionCard.module.less";

/** Tool names that should be rendered with this card */
export const SHELL_TOOL_NAMES = new Set([
  "execute_shell_command",
  "shell",
  "bash",
  "terminal",
  "run_command",
]);

/**
 * Parse the shell tool result string into structured parts.
 *
 * Backend format:
 * - Success: `<stdout>\n[stderr]\n<stderr>`
 * - Success (no output): `Command executed successfully (no output).\n[stderr]\n<stderr>`
 * - Failure: `Command failed with exit code <N>.\n[stdout]\n<stdout>\n[stderr]\n<stderr>`
 */
interface ShellResult {
  exitCode: number | null;
  stdout: string;
  stderr: string;
  raw: string;
}

function parseShellResult(result: unknown): ShellResult {
  if (result == null)
    return { exitCode: null, stdout: "", stderr: "", raw: "" };

  const raw =
    typeof result === "string" ? result : JSON.stringify(result, null, 2);

  // Check for failure header
  const failMatch = raw.match(/^Command failed with exit code (-?\d+)\./);
  const exitCode = failMatch ? parseInt(failMatch[1], 10) : 0;

  // Split by [stdout] / [stderr] markers
  let stdout = "";
  let stderr = "";

  const stderrIdx = raw.indexOf("\n[stderr]\n");
  const stdoutIdx = raw.indexOf("\n[stdout]\n");

  if (failMatch) {
    const afterHeader = raw.slice(failMatch[0].length);
    const si = afterHeader.indexOf("\n[stdout]\n");
    const ei = afterHeader.indexOf("\n[stderr]\n");

    if (si !== -1 && ei !== -1) {
      if (si < ei) {
        stdout = afterHeader.slice(si + "\n[stdout]\n".length, ei);
        stderr = afterHeader.slice(ei + "\n[stderr]\n".length);
      } else {
        stderr = afterHeader.slice(ei + "\n[stderr]\n".length, si);
        stdout = afterHeader.slice(si + "\n[stdout]\n".length);
      }
    } else if (si !== -1) {
      stdout = afterHeader.slice(si + "\n[stdout]\n".length);
    } else if (ei !== -1) {
      stderr = afterHeader.slice(ei + "\n[stderr]\n".length);
    }
  } else if (stderrIdx !== -1) {
    stdout = raw.slice(0, stderrIdx);
    stderr = raw.slice(stderrIdx + "\n[stderr]\n".length);
  } else if (stdoutIdx !== -1) {
    stdout = raw.slice(stdoutIdx + "\n[stdout]\n".length);
  } else {
    stdout = raw;
  }

  if (stdout === "Command executed successfully (no output).") {
    stdout = "";
  }

  return { exitCode, stdout: stdout.trim(), stderr: stderr.trim(), raw };
}

/** Truncate command for inline display */
function truncateCommand(cmd: string, max = 60): string {
  const oneLine = cmd.replace(/\n/g, " && ").replace(/\s+/g, " ").trim();
  return oneLine.length > max ? oneLine.slice(0, max) + "..." : oneLine;
}

interface ShellExecutionCardProps extends ToolCardProps {
  toolCallContent?: ToolCallContent;
}

const ShellExecutionCard: React.FC<ShellExecutionCardProps> = ({
  status,
  toolCallContent,
}) => {
  const { t } = useTranslation();
  const params = toolCallContent?.params || {};
  const command = (params.command as string) || "";
  const parsed = parseShellResult(toolCallContent?.result);

  const isLoading = status === "calling";
  const isError =
    status === "error" || (parsed.exitCode !== null && parsed.exitCode !== 0);
  const hasOutput = !!(parsed.stdout || parsed.stderr);

  return (
    <details
      className={`${styles.shellCard} ${isLoading ? styles.loading : ""} ${
        isError ? styles.error : ""
      }`}
      open={isLoading || isError}
    >
      {/* Summary: single-line header with icon + label + command preview */}
      <summary className={`${styles.summary} ${styles.hasIcon}`}>
        {isLoading ? (
          <span className={styles.spinner} />
        ) : (
          <span
            className={`${styles.icon} ${
              isError ? styles.iconError : styles.iconDone
            }`}
          >
            <CodeOutlined />
          </span>
        )}
        <span className={styles.label}>
          {isLoading ? t("chat.shell.executing") : t("chat.shell.execute")}
        </span>
        {command && (
          <code className={styles.commandPreview}>
            {truncateCommand(command)}
          </code>
        )}
      </summary>

      {/* Expanded content */}
      <div className={styles.body}>
        {/* Full command if truncated */}
        {command && command.length > 60 && (
          <pre className={styles.commandFull}>{command}</pre>
        )}

        {/* Output */}
        {parsed.stdout && (
          <pre className={styles.outputPre}>{parsed.stdout}</pre>
        )}

        {/* Stderr */}
        {parsed.stderr && (
          <pre className={`${styles.outputPre} ${styles.stderrPre}`}>
            {parsed.stderr}
          </pre>
        )}

        {/* Loading with no output yet */}
        {isLoading && !hasOutput && (
          <div className={styles.loadingHint}>运行中...</div>
        )}
      </div>
    </details>
  );
};

export default ShellExecutionCard;
export { parseShellResult };
