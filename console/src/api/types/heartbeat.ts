export interface ActiveHoursConfig {
  start: string;
  end: string;
}

export interface HeartbeatConfig {
  enabled: boolean;
  every: string;
  target: string;
  activeHours?: ActiveHoursConfig | null;
}
