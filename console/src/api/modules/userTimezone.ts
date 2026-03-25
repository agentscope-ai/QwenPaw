import { request } from "../request";

export interface UserTimezoneConfig {
  timezone: string;
}

export const userTimezoneApi = {
  getUserTimezone: () => request<UserTimezoneConfig>("/config/user-timezone"),

  updateUserTimezone: (timezone: string) =>
    request<UserTimezoneConfig>("/config/user-timezone", {
      method: "PUT",
      body: JSON.stringify({ timezone }),
    }),
};
