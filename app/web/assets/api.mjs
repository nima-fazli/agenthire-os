const messages = Object.freeze({
  HTTP_ERROR: "درخواست کامل نشد؛ وضعیت را تازه‌سازی کنید.",
  NETWORK_ERROR: "ارتباط با سرور برقرار نشد؛ درخواست خودکار تکرار نمی‌شود.",
  CLIENT_TIMEOUT: "مهلت انتظار پایان یافت؛ پیش از تکرار تغییر، وضعیت را تازه‌سازی کنید.",
  INVALID_RESPONSE: "پاسخ سرور قابل استفاده نبود؛ وضعیت را تازه‌سازی کنید.",
  INVALID_CREDENTIALS: "ایمیل یا رمز عبور صحیح نیست.",
  INVALID_ACCESS_TOKEN: "نشست پایان یافته است؛ دوباره وارد شوید.",
  VALIDATION_ERROR: "اطلاعات واردشده معتبر نیست؛ ورودی‌ها را بررسی کنید.",
  USER_EMAIL_ALREADY_EXISTS: "این ایمیل قبلاً ثبت شده است.",
  EMAIL_ALREADY_EXISTS: "این ایمیل قبلاً ثبت شده است.",
  ORGANIZATION_NOT_FOUND: "این سازمان در دسترس نیست.",
  ORGANIZATION_SLUG_ALREADY_EXISTS: "شناسهٔ سازمان قبلاً استفاده شده است.",
  JOB_NOT_FOUND: "این شغل در دسترس نیست.",
  CANDIDATE_NOT_FOUND: "این داوطلب در دسترس نیست.",
  JOB_MATCH_PROFILE_NOT_FOUND: "معیارهای این شغل هنوز ذخیره نشده‌اند.",
  JOB_SEARCH_PROFILE_NOT_FOUND: "عبارت جست‌وجوی این شغل هنوز ذخیره نشده است.",
  JOB_SEARCH_PROFILE_CHANGED: "پروفایل شغل تغییر کرده است؛ دوباره بازیابی کنید.",
  EXTRACTION_NOT_FOUND: "استخراج این سند هنوز درخواست نشده است.",
  EXTRACTION_NOT_READY: "استخراج سند هنوز کامل نشده است.",
  EXTRACTION_FAILED: "استخراج این سند ناموفق بوده است؛ وضعیت را بررسی کنید.",
  EXTRACTION_RETRY_LIMIT: "تعداد تلاش‌های استخراج به سقف رسیده است.",
  DOCUMENT_NOT_FOUND: "این سند در دسترس نیست.",
  DOCUMENT_STORAGE_UNAVAILABLE: "دسترسی به اسناد موقتاً برقرار نیست.",
  DOCUMENT_DELETION_PENDING: "حذف این سند هنوز کامل نشده است.",
  DOCUMENT_ALREADY_EXISTS: "این فایل قبلاً برای همین داوطلب ثبت شده است.",
  SEMANTIC_DISABLED: "بازیابی معنایی در این محیط فعال نیست.",
  EXPLANATIONS_DISABLED: "توضیح مستند در این محیط فعال نیست.",
  EMBEDDING_MODEL_NOT_INSTALLED: "مدل بازیابی محلی آماده نیست.",
  EMBEDDING_PROVIDER_UNAVAILABLE: "مدل بازیابی محلی در دسترس نیست.",
  EXPLANATION_PROVIDER_BUSY: "مدل محلی مشغول است؛ کمی بعد دوباره درخواست کنید.",
  EXPLANATION_PROVIDER_TIMEOUT: "مدل در مهلت مشخص پاسخ نداد؛ دوباره درخواست کنید.",
  EXPLANATION_MODEL_NOT_INSTALLED: "مدل توضیح محلی آماده نیست.",
  EXPLANATION_PROVIDER_UNAVAILABLE: "مدل توضیح محلی در دسترس نیست.",
  EXPLANATION_SNAPSHOT_CHANGED: "منابع یا معیارها تغییر کرده‌اند؛ توضیح تازه درخواست کنید.",
  EXPLANATION_INPUT_TOO_LARGE: "حجم شواهد از ظرفیت توضیح محلی بیشتر است.",
  EXPLANATION_OUTPUT_UNGROUNDED: "توضیح مدل با منبع سازگار نبود؛ شاهد اصلی را بررسی کنید.",
  EXPLANATION_OUTPUT_INVALID: "پاسخ مدل قابل اعتبارسنجی نبود؛ شاهد اصلی را بررسی کنید.",
});

export class ApiError extends Error {
  constructor(status, code = "HTTP_ERROR") {
    const safe = Object.hasOwn(messages, code) ? code : "HTTP_ERROR";
    super(messages[safe]); this.name = "ApiError"; this.status = status; this.code = safe;
  }
}

function validPath(path) {
  if (typeof path !== "string" || /[\u0000-\u0020\u007f\\#]/u.test(path)
      || !/^\/(?:auth\/login|users\/(?:register|me)|organizations(?:\/[A-Za-z0-9/_-]+)?)(?:\?[^#]*)?$/.test(path))
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
