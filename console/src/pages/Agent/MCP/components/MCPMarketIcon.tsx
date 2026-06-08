import styles from "./MCPMarketplaceModal.module.less";

const MCP_MARKET_ICON = "/brand/mcp-market.png";

interface MCPMarketIconProps {
  size?: number;
  className?: string;
}

/** Official MCP logo for marketplace entry points. */
export function MCPMarketIcon({ size = 16, className }: MCPMarketIconProps) {
  return (
    <img
      src={MCP_MARKET_ICON}
      alt=""
      width={size}
      height={size}
      className={[styles.mcpMarketIcon, className].filter(Boolean).join(" ")}
      draggable={false}
    />
  );
}

export function MCPMarketTitle({ title }: { title: string }) {
  return (
    <span className={styles.mcpMarketTitle}>
      <MCPMarketIcon size={22} />
      <span>{title}</span>
    </span>
  );
}
