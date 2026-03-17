export interface ProBoostAuthData {
  token: string;
  name: string;
  userId: string | number | null;
  status: boolean | null;
  lyUser: unknown;
  grantSignRewardStatus: number;
}

export interface ProBoostResponse<T> {
  success: boolean;
  code: string;
  msg: string | null;
  data: T;
}

export interface ProBoostAuthMeta {
  defaultCountryCode: string;
  supportedCountryCodes: string[];
  countryCodeOptions: ProBoostCountryCodeOption[];
}

export interface ProBoostCountryCodeOption {
  value: string;
  labelKey?: string;
}

export interface PasswordLoginPayload {
  countryCode: string;
  phone: string;
  password: string;
}

export interface SendSmsCodePayload {
  countryCode: string;
  phone: string;
  channelCode: string | null;
  deepSeekChannelCode: string | null;
}

export interface VerifySmsCodePayload {
  countryCode: string;
  phone: string;
  smsCode: string;
  channelCode: string | null;
  deepSeekChannelCode: string | null;
}

