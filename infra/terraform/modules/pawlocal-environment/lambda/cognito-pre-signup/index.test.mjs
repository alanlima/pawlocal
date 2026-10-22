import assert from "node:assert/strict";
import test from "node:test";

import { handler } from "./index.mjs";

const eventFor = (triggerSource) => ({
  triggerSource,
  request: {
    userAttributes: {
      name: "Test User",
    },
  },
  response: {},
});

test("self-service sign-up is confirmed", async () => {
  const event = eventFor("PreSignUp_SignUp");

  const result = await handler(event);

  assert.strictEqual(result, event);
  assert.equal(result.response.autoConfirmUser, true);
});

test("administrator-created users are returned unchanged", async () => {
  const event = eventFor("PreSignUp_AdminCreateUser");
  const before = structuredClone(event);

  const result = await handler(event);

  assert.strictEqual(result, event);
  assert.deepEqual(result, before);
});

test("external-provider sign-up is returned unchanged", async () => {
  const event = eventFor("PreSignUp_ExternalProvider");
  const before = structuredClone(event);

  const result = await handler(event);

  assert.strictEqual(result, event);
  assert.deepEqual(result, before);
});

test("handler does not log Cognito event or profile data", async () => {
  const original = {
    error: console.error,
    log: console.log,
    warn: console.warn,
  };
  const rejectLog = () => {
    throw new Error("The pre sign-up handler must not log event or profile data.");
  };

  console.error = rejectLog;
  console.log = rejectLog;
  console.warn = rejectLog;

  try {
    await handler(eventFor("PreSignUp_SignUp"));
  } finally {
    console.error = original.error;
    console.log = original.log;
    console.warn = original.warn;
  }
});
