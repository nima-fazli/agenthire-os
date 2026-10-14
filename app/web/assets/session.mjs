export function uuid(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value))
    throw new Error("INVALID_SCOPE");
  return value;
}
export function orgPath(org) { return `/organizations/${uuid(org)}`; }
export function jobPath(org, job) { return `${orgPath(org)}/jobs/${uuid(job)}`; }
export function candidatePath(org, candidate) { return `${orgPath(org)}/candidates/${uuid(candidate)}`; }
function record(value) { uuid(value.id); return Object.freeze({ ...value }); }
export class Session {
  #token = null; #user = null; #organization = null; #job = null; #candidate = null;
  get token() { return this.#token; }
  get user() { return this.#user; }
  get organization() { return this.#organization; }
  get job() { return this.#job; }
  get candidate() { return this.#candidate; }
  authenticate(token) {
    if (typeof token !== "string" || token.length > 4096 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(token))
      throw new Error("INVALID_SESSION");
    this.clear(); this.#token = token;
  }
  identify(user) { this.#user = record(user); }
  selectOrganization(item) {
    this.#organization = item ? record(item) : null; this.#job = this.#candidate = null;
  }
  selectJob(item) {
    if (item && item.organization_id !== this.#organization?.id) throw new Error("INVALID_SCOPE");
    this.#job = item ? record(item) : null;
  }
  selectCandidate(item) {
    if (item && item.organization_id !== this.#organization?.id) throw new Error("INVALID_SCOPE");
    this.#candidate = item ? record(item) : null;
  }
  clear() { this.#token = this.#user = this.#organization = this.#job = this.#candidate = null; }
}
