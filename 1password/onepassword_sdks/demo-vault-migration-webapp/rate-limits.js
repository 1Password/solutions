// Keeps track of service account rate limits and pauses the migration before it hits them.
// How often to ask 1Password how much of the limit is left.
const CHECK_INTERVAL_MS = 30 * 1000;
const CHECK_EVERY_REQUESTS = 25;
const MIN_PAUSE_MS = Number(process.env.RATE_LIMIT_MIN_PAUSE_MS) || 5 * 1000;
const DEFAULT_PAUSE_MS = 60 * 1000;

export class MigrationCancelledError extends Error {
  constructor() {
    super('Migration cancelled by user');
    this.name = 'MigrationCancelledError';
  }
}

export function parseDuration(text) {
  const t = String(text ?? '').toLowerCase().trim();
  if (!t || t === 'n/a' || t === '-' || t === 'never') return null;
  if (t.includes('less than a minute')) return 60 * 1000;
  if (t === 'now') return 0;

  const normalized = t.replace(/\b(an?)\s+(?=(second|minute|hour|day))/g, '1 ');
  const unitMs = { d: 86400000, h: 3600000, m: 60000, s: 1000 };
  const pattern = /(\d+(?:\.\d+)?)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)(?![a-z])/g;
  let total = 0;
  let found = false;
  for (const [, amount, unit] of normalized.matchAll(pattern)) {
    total += Number(amount) * unitMs[unit[0]];
    found = true;
  }
  return found ? Math.round(total) : null;
}

export function parseRetryAfter(message) {
  const match = /retry (?:in|after) ([^.,;]+)/i.exec(String(message ?? ''));
  return match ? parseDuration(match[1]) : null;
}

export function parseRateLimitTable(text) {
  const entries = {};
  for (const line of String(text ?? '').split('\n')) {
    const parts = line.trim().split(/\s+/);
    if (parts.length < 5 || parts[0].toUpperCase() === 'TYPE') continue;
    const [type, action, limit, used, remaining, ...reset] = parts;
    if (![limit, used, remaining].every(v => /^\d+$/.test(v))) continue;
    entries[`${type.toLowerCase()}:${action.toLowerCase()}`] = {
      scope: type.toLowerCase(),
      action: action.toLowerCase(),
      limit: Number(limit),
      used: Number(used),
      remaining: Number(remaining),
      resetInMs: parseDuration(reset.join(' ')),
    };
  }
  if (Object.keys(entries).length === 0) {
    throw new Error(`Could not read rate limits from op output: ${String(text).slice(0, 200)}`);
  }
  return entries;
}

const newCounters = () => ({
  read: { requests: 0, batchRequests: 0, batchUnits: 0, cost: 0 },
  write: { requests: 0, batchRequests: 0, batchUnits: 0, cost: 0 },
});

export class RateLimitMonitor {
  static #byToken = new Map();

  static for(token, label, deps) {
    let monitor = RateLimitMonitor.#byToken.get(token);
    if (!monitor) {
      monitor = new RateLimitMonitor({ token, label, ...deps });
      RateLimitMonitor.#byToken.set(token, monitor);
    }
    monitor.label = label;
    return monitor;
  }

  constructor({ token, label, runOp, log }) {
    this.token = token;
    this.label = label;
    this.runOp = runOp;
    this.log = log;
    this.entries = null;
    this.fetchedAt = 0;
    this.supported = true;
    this.lastFailureAt = 0;
    this.since = newCounters();
    // null means we don't know yet whether a batch counts once or once per item.
    this.countsPerItem = { read: null, write: null };
    this.lockTail = Promise.resolve();
  }

  exclusive(fn) {
    const run = this.lockTail.then(fn, fn);
    this.lockTail = run.catch(() => {});
    return run;
  }

  async refresh() {
    if (!this.supported) return false;
    let output;
    try {
      output = await this.runOp(['service-account', 'ratelimit'], { token: this.token });
    } catch (error) {
      const detail = (error.stderr || error.message || '').trim().split('\n').pop();
      this.lastFailureAt = Date.now();
      if (/unknown (command|flag)/i.test(detail)) {
        this.supported = false;
        this.log.warning(null, `This op CLI can't report rate limits (${detail}). Update it for early pauses; until then the migration pauses when 1Password reports a limit.`);
      } else {
        this.log.warning(null, `Could not read ${this.label} rate limits (${detail}). Will try again; meanwhile the migration pauses if 1Password reports a limit.`);
      }
      return false;
    }
    const entries = parseRateLimitTable(output);
    this.#learn(entries);
    this.entries = entries;
    this.fetchedAt = Date.now();
    this.lastFailureAt = 0;
    this.since = newCounters();
    return true;
  }

  #learn(entries) {
    for (const kind of ['read', 'write']) {
      const before = this.entries?.[`token:${kind}`];
      const after = entries[`token:${kind}`];
      const { requests, batchRequests, batchUnits } = this.since[kind];
      if (!before || !after || batchUnits <= batchRequests) continue;
      const delta = after.used - before.used - requests;
      if (delta < 0) continue;
      const previous = this.countsPerItem[kind];
      if (delta <= batchRequests + 1) this.countsPerItem[kind] = false;
      else if (delta >= batchUnits - 1) this.countsPerItem[kind] = true;
      if (previous !== this.countsPerItem[kind] && this.countsPerItem[kind] !== null) {
        this.log.info(null, `${this.label} service account: batched ${kind}s count ${this.countsPerItem[kind] ? 'once per item' : 'once per request'}`);
      }
    }
  }

  cost(kind, requests, units) {
    return this.countsPerItem[kind] === false ? requests : Math.max(requests, units);
  }

  #constraints(kind) {
    if (!this.entries) return [];
    const now = Date.now();
    return Object.entries(this.entries)
      // Limits we guessed from a 429 run out at the reset time.
      .filter(([, e]) => !(e.assumed && this.fetchedAt + e.resetInMs <= now))
      .filter(([, e]) => (e.scope === 'token' && e.action === kind)
        || (e.scope === 'account' && (e.action === kind || e.action === 'read_write')))
      .map(([key, e]) => {
        const spent = e.scope === 'token' || e.action === kind
          ? this.since[kind].cost
          : this.since.read.cost + this.since.write.cost;
        return {
          key, ...e,
          available: e.remaining - spent,
          resetAt: e.resetInMs === null ? null : this.fetchedAt + e.resetInMs,
        };
      });
  }

  limiting(kind) {
    const list = this.#constraints(kind);
    if (list.length === 0) return null;
    return list.reduce((a, b) => (b.available < a.available ? b : a));
  }

  // Keep a few requests spare in case something else is using the same token.
  reserve(kind) {
    const token = this.entries?.[`token:${kind}`];
    return Math.max(3, Math.ceil((token?.limit ?? 0) * 0.02));
  }

  record(kind, requests, units, { batch = false } = {}) {
    const c = this.since[kind];
    if (batch) {
      c.batchRequests += requests;
      c.batchUnits += units;
    } else {
      c.requests += requests;
    }
    c.cost += batch ? this.cost(kind, requests, units) : requests;
  }

  assumePerItem(kind) {
    this.countsPerItem[kind] = true;
  }

  needsCheck(kind, cost) {
    if (!this.supported) return false;
    if (this.lastFailureAt && Date.now() - this.lastFailureAt < 15000) return false;
    if (!this.entries) return true;
    if (Date.now() - this.fetchedAt > CHECK_INTERVAL_MS) return true;
    const sent = (k) => this.since[k].requests + this.since[k].batchRequests;
    if (sent('read') + sent('write') >= CHECK_EVERY_REQUESTS) return true;
    const limiting = this.limiting(kind);
    return !!limiting && limiting.available - cost < this.reserve(kind) * 3 + cost;
  }

  markExhausted(kind, retryAfterMs) {
    const key = `token:${kind}`;
    const resetInMs = retryAfterMs ?? this.entries?.[key]?.resetInMs ?? DEFAULT_PAUSE_MS;
    this.entries = { ...(this.entries || {}) };
    const existing = this.entries[key];
    this.entries[key] = { scope: 'token', action: kind, limit: existing?.limit ?? 0, used: existing?.limit ?? 0, remaining: 0, resetInMs, assumed: true };
    this.fetchedAt = Date.now();
    this.since = newCounters();
  }

  snapshot() {
    if (!this.entries) return { label: this.label, supported: this.supported, limits: [] };
    return {
      label: this.label,
      supported: this.supported,
      limits: Object.values(this.entries).map(e => ({
        scope: e.scope, action: e.action, limit: e.limit, used: e.used, remaining: e.remaining,
        resetAt: e.resetInMs === null ? null : this.fetchedAt + e.resetInMs,
      })),
    };
  }
}

export class MigrationControl {
  constructor({ id, emit, log }) {
    this.id = id;
    this.emit = emit;
    this.log = log;
    this.cancelled = false;
    this.clientConnected = true;
    this.waiters = new Set();
    this.pausedNow = false;
  }

  throwIfCancelled() {
    if (this.cancelled) throw new MigrationCancelledError();
  }

  get isPaused() {
    return this.waiters.size > 0;
  }

  cancel() {
    this.cancelled = true;
    for (const waiter of this.waiters) waiter.resolve('cancel');
  }

  resume() {
    if (this.waiters.size === 0) return false;
    for (const waiter of this.waiters) waiter.resolve('resume');
    return true;
  }

  // A page is watching again, so pauses wait for its Resume click instead of resuming on their own.
  clientReconnected() {
    this.clientConnected = true;
  }

  clientDisconnected() {
    this.clientConnected = false;
    for (const waiter of this.waiters) this.#scheduleAutoResume(waiter);
  }

  #scheduleAutoResume(waiter) {
    clearTimeout(waiter.timer);
    waiter.timer = setTimeout(() => waiter.resolve('resume'), Math.max(0, waiter.resumeAt - Date.now()));
  }

  reportUsage(monitor) {
    this.emit({ rateLimitEvent: 'usage', usage: monitor.snapshot() });
  }

  async pause(monitor, kind, needed, { reason = 'approaching', retryAfterMs = null } = {}) {
    const limiting = monitor.limiting(kind);
    const now = Date.now();
    const resetAt = limiting?.resetAt ?? (retryAfterMs !== null ? now + retryAfterMs : now + DEFAULT_PAUSE_MS);
    const resumeAt = Math.max(resetAt, now + MIN_PAUSE_MS);

    this.pausedNow = true;
    const details = {
      label: monitor.label,
      kind,
      scope: limiting?.scope ?? 'token',
      limit: limiting?.limit ?? null,
      used: limiting?.used ?? null,
      remaining: limiting ? Math.max(0, limiting.available) : null,
      needed,
      reserve: monitor.reserve(kind),
      reason,
      resumeAt,
      serverTime: now,
    };
    this.log.warning(null, `Paused: ${monitor.label} service account ${reason === 'hit' ? 'hit' : 'is close to'} its ${details.scope} ${kind} limit `
      + `(${details.remaining ?? '?'} left, need ${needed}). Can resume at ${new Date(resumeAt).toISOString()}.`);
    this.emit({ rateLimitEvent: 'paused', pause: details });

    const waiter = { resumeAt, timer: null, resolve: null };
    const outcome = await new Promise(resolve => {
      waiter.resolve = resolve;
      this.waiters.add(waiter);
      if (this.cancelled) resolve('cancel');
      else if (!this.clientConnected) this.#scheduleAutoResume(waiter);
    });
    clearTimeout(waiter.timer);
    this.waiters.delete(waiter);

    if (outcome === 'cancel') throw new MigrationCancelledError();
    this.log.info(null, `Resume requested, checking ${monitor.label} rate limits before continuing`);
    this.emit({ rateLimitEvent: 'checking' });
  }

  resumed() {
    if (!this.pausedNow || this.waiters.size > 0) return;
    this.pausedNow = false;
    this.log.info(null, 'Enough rate limit room, migration resumed');
    this.emit({ rateLimitEvent: 'resumed' });
  }
}

// Waits until there's room under the limit, pausing for the user if needed.
export async function acquire({ monitor, control }, kind, { requests = 1, units = 1, flexible = false } = {}) {
  const batch = units > 1;
  return monitor.exclusive(async () => {
    for (;;) {
      control.throwIfCancelled();

      const costOf = (n) => (batch ? monitor.cost(kind, 1, n) : requests);
      if (monitor.needsCheck(kind, costOf(units))) {
        await monitor.refresh();
        control.reportUsage(monitor);
      }

      const limiting = monitor.limiting(kind);
      if (!limiting) {
        monitor.record(kind, batch ? 1 : requests, units, { batch });
        return units;
      }

      const reserve = monitor.reserve(kind);
      const room = limiting.available - reserve;
      const ceiling = Math.max(1, limiting.limit - reserve);
      let grant = units;
      if (flexible && costOf(units) > room) grant = Math.max(0, Math.min(units, Math.floor(room)));
      if (grant >= 1 && Math.min(costOf(grant), ceiling) <= room) {
        monitor.record(kind, batch ? 1 : requests, grant, { batch: grant > 1 });
        control.resumed();
        return grant;
      }

      await control.pause(monitor, kind, Math.min(costOf(flexible ? 1 : units), ceiling));
      await monitor.refresh();
      control.reportUsage(monitor);
    }
  });
}

// 1Password said 429 anyway, so pause until it says we can try again.
export async function waitOutRateLimit({ monitor, control }, kind, error) {
  const retryAfterMs = parseRetryAfter(error?.message);
  await monitor.exclusive(async () => {
    await monitor.refresh();
    const limiting = monitor.limiting(kind);
    if (!limiting || limiting.available - monitor.reserve(kind) >= 1) {
      monitor.markExhausted(kind, retryAfterMs);
    }
    control.reportUsage(monitor);
    await control.pause(monitor, kind, 1, { reason: 'hit', retryAfterMs });
    await monitor.refresh();
    control.reportUsage(monitor);
  });
}
