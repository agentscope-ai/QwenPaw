import assert from "node:assert/strict";
import test from "node:test";

import {
  isValidPlatformEmail,
  isValidPlatformPassword,
  platformConnectionKeysForLogout,
  platformRegistrationError,
} from "./authModel";

const localConnection = {
  agentId: "default",
  baseUrl: "http://192.168.1.23:8088",
  source: "private" as const,
  token: "local-token",
  username: "",
};

const firstPlatformConnection = {
  agentId: "default",
  baseUrl: "https://first.example.com",
  source: "platform" as const,
  token: "first-token",
  username: "platform",
};

const secondPlatformConnection = {
  agentId: "default",
  baseUrl: "https://second.example.com",
  source: "platform" as const,
  token: "second-token",
  username: "platform",
};

test("validates Platform registration email and password rules", () => {
  assert.equal(isValidPlatformEmail("user@example.com"), true);
  assert.equal(isValidPlatformEmail("user"), false);
  assert.equal(isValidPlatformPassword("a1234567"), true);
  assert.equal(isValidPlatformPassword("12345678"), false);
  assert.equal(isValidPlatformPassword("a123"), false);
});

test("returns the first actionable registration error", () => {
  assert.equal(platformRegistrationError({
    account: "user@example.com",
    confirmPassword: "a1234567",
    password: "a1234567",
    verifyCode: "123456",
  }), null);
  assert.equal(platformRegistrationError({
    account: "user@example.com",
    confirmPassword: "b1234567",
    password: "a1234567",
    verifyCode: "123456",
  }), "两次输入的密码不一致");
});

test("Platform logout removes only Platform connections", () => {
  assert.deepEqual(platformConnectionKeysForLogout(
    [localConnection, firstPlatformConnection],
    localConnection,
  ), ["platform:https://first.example.com"]);
});

test("Platform logout removes the active cloud connection last", () => {
  assert.deepEqual(platformConnectionKeysForLogout(
    [firstPlatformConnection, localConnection, secondPlatformConnection],
    firstPlatformConnection,
  ), [
    "platform:https://second.example.com",
    "platform:https://first.example.com",
  ]);
});
