import { defaultCountryCode } from "./proboost/config";
import {
  loginWithPassword,
  sendSmsCode,
  verifySmsCode,
} from "./proboost/client";
import type { ProBoostResponse, ProBoostAuthData } from "./proboost/types";

export async function loginByPassword(
  phone: string,
  password: string,
  countryCode: string = defaultCountryCode,
): Promise<ProBoostResponse<ProBoostAuthData>> {
  return loginWithPassword({
    countryCode,
    phone,
    password,
  });
}

export async function logoutRequest(): Promise<void> {
  return Promise.resolve();
}

export async function sendRegisterSmsCode(
  phone: string,
  countryCode: string = defaultCountryCode,
): Promise<ProBoostResponse<boolean>> {
  return sendSmsCode({
    countryCode,
    phone,
    channelCode: null,
    deepSeekChannelCode: null,
  });
}

export async function registerBySmsCode(
  phone: string,
  smsCode: string,
  countryCode: string = defaultCountryCode,
): Promise<ProBoostResponse<ProBoostAuthData>> {
  return verifySmsCode({
    countryCode,
    phone,
    smsCode,
    channelCode: null,
    deepSeekChannelCode: null,
  });
}


