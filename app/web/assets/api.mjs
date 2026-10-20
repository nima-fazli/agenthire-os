const messages = Object.freeze({
  HTTP_ERROR: "The request could not be completed. Refresh the current state.",
  NETWORK_ERROR: "The server could not be reached. The request was not retried automatically.",
  CLIENT_TIMEOUT: "The request timed out. Refresh the current state before repeating a change.",
  INVALID_RESPONSE: "The server response could not be verified. Refresh the current state.",
  INVALID_CREDENTIALS: "The email or password is incorrect.",
  INVALID_ACCESS_TOKEN: "Your session has expired. Sign in again.",
  AUTH_THROTTLED: "Too many unsuccessful attempts. Try again in 15 minutes.",
  AUTH_BUSY: "Password verification is busy. Try again shortly.",
  INVALID_CURRENT_PASSWORD: "The current password is incorrect. No change was saved.",
  REAUTHENTICATION_REQUIRED: "Your credentials have changed. Verify your current password again.",
  PASSWORD_UNCHANGED: "Your new password must differ from your current password.",
  PERMISSION_DENIED: "Your role does not allow this change.",
  LAST_OWNER: "The organization must retain at least one active owner.",
  ACCESS_CHANGED: "The member role has changed. Refresh the member list.",
  ACCESS_BUSY: "Another access change is in progress. Refresh the list shortly.",
  MEMBER_NOT_FOUND: "This member is no longer available.",
  MEMBER_ALREADY_EXISTS: "This account is already a member. Change its role separately.",
  INVITATION_ALREADY_EXISTS: "An active invitation already exists for this email.",
  INVITATION_LIMIT: "The limit of 20 active invitations has been reached. Review existing invitations.",
  INVITATION_INVALID: "The invitation code is invalid for this account, expired, or already used.",
  VALIDATION_ERROR: "The submitted information is invalid. Check the form fields.",
  USER_EMAIL_ALREADY_EXISTS: "This email is already registered.",
  EMAIL_ALREADY_EXISTS: "This email is already registered.",
  ORGANIZATION_NOT_FOUND: "This organization is not available.",
  ORGANIZATION_SLUG_ALREADY_EXISTS: "This organization slug is already in use.",
  JOB_NOT_FOUND: "This job is not available.",
  CANDIDATE_NOT_FOUND: "This candidate is not available.",
  APPLICATION_NOT_FOUND: "This application is not available.",
  APPLICATION_ALREADY_EXISTS: "This candidate has already applied for this job.",
  INVALID_APPLICATION_STATUS_TRANSITION: "The application changed or this transition is not allowed. Refresh the list.",
  RECORD_CHANGED: "This record has changed concurrently. Load the latest version and review your edits.",
  RECORD_BUSY: "Another edit is in progress. Load the latest version shortly.",
  PAGE_QUERY_TIMEOUT: "Search exceeded its time limit. Narrow your query.",
  JOB_MATCH_PROFILE_NOT_FOUND: "The criteria for this job have not been saved yet.",
  JOB_SEARCH_PROFILE_NOT_FOUND: "The search query for this job has not been saved yet.",
  JOB_SEARCH_PROFILE_CHANGED: "The job profile has changed. Run retrieval again.",
  EXTRACTION_NOT_FOUND: "Extraction has not been requested for this document.",
  EXTRACTION_NOT_READY: "Document extraction is not complete yet.",
  EXTRACTION_FAILED: "Document extraction failed. Check its status.",
  EXTRACTION_RETRY_LIMIT: "The extraction attempt limit has been reached.",
  DOCUMENT_NOT_FOUND: "This document is not available.",
  DOCUMENT_STORAGE_UNAVAILABLE: "Document storage is temporarily unavailable.",
  DOCUMENT_DELETION_PENDING: "Document deletion has not completed yet.",
  DOCUMENT_ALREADY_EXISTS: "This file already exists for this candidate.",
  SEMANTIC_DISABLED: "Semantic retrieval is disabled in this environment.",
  EXPLANATIONS_DISABLED: "Grounded briefs are disabled in this environment.",
  EMBEDDING_MODEL_NOT_INSTALLED: "The local retrieval model is not installed.",
  EMBEDDING_PROVIDER_UNAVAILABLE: "The local retrieval model is unavailable.",
  DOCUMENT_CHUNKS_NOT_READY: "Complete document extraction and chunking first.",
  EMBEDDING_SOURCE_LIMIT: "This document exceeds the semantic processing chunk limit.",
  EMBEDDING_RETRY_LIMIT: "The semantic processing attempt limit has been reached.",
  EMBEDDING_JOB_NOT_FOUND: "This embedding job is unavailable. Refresh the document status.",
  EXPLANATION_PROVIDER_BUSY: "The local model is busy. Try again shortly.",
  EXPLANATION_PROVIDER_TIMEOUT: "The local model timed out. Request a new brief.",
  EXPLANATION_MODEL_NOT_INSTALLED: "The local brief model is not installed.",
  EXPLANATION_PROVIDER_UNAVAILABLE: "The local brief model is unavailable.",
  EXPLANATION_SNAPSHOT_CHANGED: "Sources or criteria have changed. Request a new brief.",
  EXPLANATION_INPUT_TOO_LARGE: "The evidence exceeds the local brief input budget.",
  EXPLANATION_OUTPUT_UNGROUNDED: "The model output did not match its source. Review the original evidence.",
  EXPLANATION_OUTPUT_INVALID: "The model output could not be validated. Review the original evidence.",
});

export class ApiError extends Error {
  constructor(status, code = "HTTP_ERROR") {
    const safe = Object.hasOwn(messages, code) ? code : "HTTP_ERROR";
    super(messages[safe]); this.name = "ApiError"; this.status = status; this.code = safe;
  }
}

function validPath(path) {
  if (typeof path !== "string" || /[\u0000-\u0020\u007f\\#]/u.test(path)
      || !/^\/(?:auth\/(?:login|logout|password|sessions(?:\/[A-Za-z0-9_-]+)?)|access\/invitations\/accept|users\/(?:register|me)|organizations(?:\/[A-Za-z0-9/_-]+)?)(?:\?[^#]*)?$/.test(path))
    throw new Error("INVALID_API_PATH");
}

const aborted = () => new DOMException("Request cancelled", "AbortError");

async function readBody(response, limit, pdf = false) {
  const type = response.headers?.get("content-type") ?? "";
  if (pdf ? !/^application\/pdf(?:;|$)/i.test(type) : type && !/^application\/json(?:;|$)/i.test(type))
    throw new ApiError(response.status, "INVALID_RESPONSE");

  const declared = Number(response.headers?.get("content-length"));
  if (Number.isFinite(declared) && declared > limit)
    throw new ApiError(response.status, "INVALID_RESPONSE");

  if (!response.body?.getReader) {
    const result = pdf ? await response.blob() : await response.json();
    if (pdf && result.size > limit)
      throw new ApiError(response.status, "INVALID_RESPONSE");
    return result;
  }

  const reader = response.body.getReader(), pieces = [];
  let size = 0;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit)
        throw new ApiError(response.status, "INVALID_RESPONSE");
      pieces.push(value);
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }

  const body = new Blob(pieces, {
    type: pdf ? "application/pdf" : "application/json",
  });

  if (pdf) return body;
  return JSON.parse(await body.text());
}

export class ApiClient {
  constructor(token, unauthorized, transport = (...args) => fetch(...args)) {
    this.token = token;
    this.unauthorized = unauthorized;
    this.transport = transport;
  }

  async request(
    path,
    {
      method = "GET",
      data,
      body,
      signal,
      timeout = 20000,
      blob = false,
    } = {},
  ) {
    validPath(path);

    if (!["GET", "POST", "PUT", "PATCH", "DELETE"].includes(method)
        || !Number.isInteger(timeout) || timeout < 1 || timeout > 185000
        || (data !== undefined && body !== undefined))
      throw new Error("INVALID_API_REQUEST");

    const controller = new AbortController(), captured = this.token();
    const publicPath = path === "/auth/login" || path === "/users/register";

    let timedOut = false, rejectAbort;
    const interruption = new Promise((_, reject) => {
      rejectAbort = reject;
    });

    const relay = () => controller.abort();
    const onAbort = () => rejectAbort(aborted());

    controller.signal.addEventListener("abort", onAbort, { once: true });
    signal?.addEventListener("abort", relay, { once: true });

    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeout);

    try {
      if (signal?.aborted) relay();

      const headers = {
        Accept: blob ? "application/pdf" : "application/json",
      };

      if (captured && !publicPath)
        headers.Authorization = "Bearer " + captured;
      if (data !== undefined)
        headers["Content-Type"] = "application/json";
      if (body !== undefined)
        headers["Content-Type"] = "application/pdf";

      const task = (async () => {
        const response = await this.transport(path, {
          method,
          headers,
          body: data === undefined ? body : JSON.stringify(data),
          signal: controller.signal,
          credentials: "omit",
          redirect: "error",
          cache: "no-store",
        });

        if (controller.signal.aborted) throw aborted();

        if (!response.ok) {
          if (response.status === 401 && !publicPath
              && captured && this.token() === captured)
            this.unauthorized();

          let code = "HTTP_ERROR";

          try {
            code = (await readBody(response, 65536))?.error?.code ?? code;
          } catch {
            if (controller.signal.aborted) throw aborted();
          }

          throw new ApiError(response.status, code);
        }

        if (response.status === 204) return null;

        try {
          return await readBody(
            response,
            blob ? 10 * 1024 * 1024 : 2 * 1024 * 1024,
            blob,
          );
        } catch (error) {
          if (controller.signal.aborted || error.name === "AbortError")
            throw aborted();
          throw new ApiError(response.status, "INVALID_RESPONSE");
        }
      })();

      return await Promise.race([task, interruption]);
    } catch (error) {
      if (timedOut) throw new ApiError(0, "CLIENT_TIMEOUT");
      if (controller.signal.aborted || error.name === "AbortError")
        throw aborted();
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, "NETWORK_ERROR");
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", relay);
      controller.signal.removeEventListener("abort", onAbort);
      controller.abort();
    }
  }
}
