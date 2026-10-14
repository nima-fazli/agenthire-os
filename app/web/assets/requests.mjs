export class RequestGate {
  #epoch = 0; #tasks = new Map();
  get epoch() { return this.#epoch; }
  get keys() { return [...this.#tasks.keys()]; }
  has(key) { return this.#tasks.has(key); }
  cancel(key) {
    this.#tasks.get(key)?.controller.abort(); this.#tasks.delete(key);
  }
  reset() {
    for (const key of this.keys) this.cancel(key);
    this.#epoch += 1;
  }
  async run(key, work, replace = true) {
    if (this.has(key) && !replace) throw new Error("REQUEST_BUSY");
    this.cancel(key);
    const task = { controller: new AbortController(), epoch: this.#epoch };
    this.#tasks.set(key, task);
    const current = () => !task.controller.signal.aborted && task.epoch === this.#epoch && this.#tasks.get(key) === task;
    try {
      const value = await work(task.controller.signal);
      if (!current()) throw new DOMException("Discarded request", "AbortError");
      return value;
    } catch (error) {
      if (!current()) throw new DOMException("Discarded request", "AbortError");
      throw error;
    } finally {
      task.controller.abort();
      if (this.#tasks.get(key) === task) this.#tasks.delete(key);
    }
  }
}
