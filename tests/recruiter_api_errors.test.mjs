import test from "node:test";
import assert from "node:assert/strict";
import { ApiClient } from "../app/web/assets/api.mjs";

const response = (code, status) => new Response(JSON.stringify({
  error: { code, message: "PRIVATE_SERVER_TEXT" },
}), { status, headers: { "Content-Type": "application/json" } });

for (const code of ["USER_EMAIL_ALREADY_EXISTS", "EMAIL_ALREADY_EXISTS"]) {
  test(`duplicate registration uses a safe English message: ${code}`, async () => {
    let calls = 0;
    const client = new ApiClient(() => null, () => assert.fail(), async () => {
      calls++;
      return response(code, 409);
    });
    await assert.rejects(client.request("/users/register", {
      method: "POST", data: { email: "fixture@example.com", password: "private" },
    }), error => error.status === 409 && error.code === code
      && error.message === "This email is already registered.");
    assert.equal(calls, 1);
  });
}

for (const code of ["EXPLANATION_OUTPUT_UNGROUNDED", "EXPLANATION_OUTPUT_INVALID"]) {
  test(`invalid model output has a safe English error: ${code}`, async () => {
    let calls = 0;
    const client = new ApiClient(() => "token", () => {}, async () => {
      calls++;
      return response(code, 503);
    });
    await assert.rejects(client.request("/organizations"), error =>
      error.status === 503 && error.code === code && error.message.includes("original evidence")
      && !error.message.includes("PRIVATE_SERVER_TEXT"));
    assert.equal(calls, 1);
  });
}
