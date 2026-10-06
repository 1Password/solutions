import sdk from '@1password/sdk';
import { execFile } from 'child_process';
import { promisify } from 'util';
import crypto from 'crypto';
import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import https from 'https';
import selfsigned from 'selfsigned';
import fs from 'fs';
import { createInterface } from 'readline';
import {
  RateLimitMonitor, MigrationControl, MigrationCancelledError, acquire, waitOutRateLimit,
} from './rate-limits.js';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const execFileAsync = promisify(execFile);

const migrationSessions = new Map();
const SESSION_TTL = 5 * 60 * 1000;

const PORT = Number(process.env.PORT) || 3001;
// Only reachable from this machine unless HOST is set. The app has no login.
const HOST = process.env.HOST || '127.0.0.1';

let envConfig = {
  loaded: false,
  authMode: null,
  sourceToken: null,
  destToken: null,
  sourceAccount: null,
  destAccount: null,
};

function loadEnvFile() {
  const envPath = path.join(__dirname, '.env');
  console.log(`[startup] Looking for .env at: ${envPath}`);

  try {
    const content = fs.readFileSync(envPath, 'utf8');
    console.log(`[startup] .env file read successfully (${content.length} bytes)`);

    const lines = content.split('\n');
    const vars = {};
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx === -1) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      let val = trimmed.slice(eqIdx + 1).trim();

      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      vars[key] = val;
    }

    const varKeys = Object.keys(vars);
    console.log(`[startup] .env parsed, found keys: ${varKeys.join(', ')}`);

    envConfig.loaded = true;
    envConfig.authMode = vars.AUTH_MODE || null;
    envConfig.sourceToken = vars.SOURCE_TOKEN || null;
    envConfig.destToken = vars.DEST_TOKEN || null;
    envConfig.sourceAccount = vars.SOURCE_ACCOUNT || null;
    envConfig.destAccount = vars.DEST_ACCOUNT || null;

    const VALID_AUTH_MODES = ['service-account', 'desktop'];
    if (envConfig.authMode && !VALID_AUTH_MODES.includes(envConfig.authMode)) {
      console.log(`[startup] Auth mode: invalid value (not 'service-account' or 'desktop'), falling back to auto-detect`);
      envConfig.authMode = null;
    }

    if (!envConfig.authMode) {
      if (envConfig.sourceToken || envConfig.destToken) {
        envConfig.authMode = 'service-account';
      } else if (envConfig.sourceAccount || envConfig.destAccount) {
        envConfig.authMode = 'desktop';
      }
    }

    console.log(`[startup] Auth mode: ${envConfig.authMode || 'not set'}`);
    console.log(`[startup] Source token: ${envConfig.sourceToken ? '✓ present' : '✗ missing'}`);
    console.log(`[startup] Dest token: ${envConfig.destToken ? '✓ present' : '✗ missing'}`);
    console.log(`[startup] Source account: ${envConfig.sourceAccount || 'not set'}`);
    console.log(`[startup] Dest account: ${envConfig.destAccount || 'not set'}`);

    return true;
  } catch (err) {
    if (err.code === 'ENOENT') {
      console.log(`[startup] No .env file found, using manual token entry`);
    } else {
      console.warn(`[startup] Could not read .env file: ${err.message}`);
    }
    return false;
  }
}
loadEnvFile();

const app = express();
const LOG_DIR = process.env.LOG_DIR || path.join(__dirname, 'logs');
const MAX_FAILED_ITEMS_IN_MEMORY = 5000;

// Log lines go to a file instead of memory, so long runs don't use up RAM.
class LogManager {
  constructor() {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    this.logPath = path.join(LOG_DIR, `migration-${stamp}.log`);
    this.fd = fs.openSync(this.logPath, 'a', 0o600);
    this.resetCounters();
  }

  resetCounters() {
    this.totalEntries = 0;
    this.errorCount = 0;
    this.warningCount = 0;
    this.vaultIds = new Set();
    this.failedItems = [];
    this.failedItemCount = 0;
    this.failedVaults = [];
    this.vaultSummaries = {};
  }

  log(level, vaultId, message, metadata = {}) {
    const timestamp = new Date().toISOString();
    this.totalEntries++;
    if (vaultId) this.vaultIds.add(vaultId);
    if (level === 'ERROR') this.errorCount++;
    if (level === 'WARNING') this.warningCount++;

    const line = `[${timestamp}] [${level}]${vaultId ? ` [Vault: ${vaultId}]` : ''}${metadata.itemId ? ` [Item: ${metadata.itemId}]` : ''} ${message}`;
    try {
      fs.writeSync(this.fd, line + '\n');
    } catch (error) {
      console.error(`Could not write to log file ${this.logPath}: ${error.message}`);
    }

    const prefix = `[${timestamp}] [${level}]${vaultId ? ` [${vaultId}]` : ''}`;
    console.log(`${prefix} ${message}`);
  }

  info(vaultId, message, metadata = {}) { this.log('INFO', vaultId, message, metadata); }
  warning(vaultId, message, metadata = {}) { this.log('WARNING', vaultId, message, metadata); }
  error(vaultId, message, metadata = {}) { this.log('ERROR', vaultId, message, metadata); }

  logFailedItem(vaultId, vaultName, itemId, itemTitle, error) {
    this.failedItemCount++;
    if (this.failedItems.length < MAX_FAILED_ITEMS_IN_MEMORY) {
      this.failedItems.push({
        vaultId, vaultName, itemId, itemTitle,
        error: error.message || error.toString(),
        timestamp: new Date().toISOString()
      });
    }
    this.error(vaultId, `Failed to migrate item [${itemId}] "${itemTitle}": ${error.message}`, { itemId });
  }

  logFailedVault(vaultId, vaultName, error) {
    this.failedVaults.push({
      vaultId, vaultName,
      error: typeof error === 'string' ? error : (error.message || error.toString()),
      timestamp: new Date().toISOString()
    });
    this.error(vaultId, `Vault "${vaultName}" failed: ${typeof error === 'string' ? error : error.message}`);
  }

  logVaultComplete(vaultId, vaultName, stats) {
    this.vaultSummaries[vaultId] = {
      vaultName,
      sourceItemCount: stats.sourceItemCount,
      destItemCount: stats.destItemCount,
      successCount: stats.successCount,
      failureCount: stats.failureCount,
      timestamp: new Date().toISOString()
    };
  }

  async pipeGlobalLog(out) {
    await new Promise((resolve, reject) => {
      const stream = fs.createReadStream(this.logPath);
      stream.on('error', reject);
      stream.on('end', resolve);
      stream.pipe(out, { end: false });
    });
  }

  async getVaultLog(vaultId) {
    const tag = ` [Vault: ${vaultId}]`;
    const lines = [];
    const reader = createInterface({ input: fs.createReadStream(this.logPath), crlfDelay: Infinity });
    for await (const line of reader) {
      if (line.includes(tag)) lines.push(line.replace(tag, ''));
    }
    return lines.join('\n');
  }

  getSummary() {
    return {
      totalEntries: this.totalEntries,
      errors: this.errorCount,
      warnings: this.warningCount,
      vaults: this.vaultIds.size,
      failedItems: this.failedItemCount,
      failedVaults: this.failedVaults.length
    };
  }

  getFailureSummary() {
    const hasFailedItems = this.failedItemCount > 0;
    const hasFailedVaults = this.failedVaults.length > 0;

    if (!hasFailedItems && !hasFailedVaults) {
      return '\n═══════════════════════════════════════════════════════════════════════════════\n' +
             '✓ NO FAILED ITEMS - All items migrated successfully!\n' +
             '═══════════════════════════════════════════════════════════════════════════════\n';
    }

    let summary = '\n';
    summary += '═══════════════════════════════════════════════════════════════════════════════\n';

    if (hasFailedVaults) {
      summary += `FAILED VAULTS (${this.failedVaults.length} vault(s) could not be read or written)\n`;
      summary += '═══════════════════════════════════════════════════════════════════════════════\n\n';
      this.failedVaults.forEach((v, i) => {
        summary += `  ${i + 1}. Vault: "${v.vaultName}"\n     UUID:  ${v.vaultId}\n     Error: ${v.error}\n     Time:  ${v.timestamp}\n\n`;
      });
    }

    if (hasFailedItems) {
      summary += `FAILED ITEMS SUMMARY (${this.failedItemCount} total failures)\n`;
      if (this.failedItemCount > this.failedItems.length) {
        summary += `(showing the first ${this.failedItems.length}; every failure is in the detailed log below)\n`;
      }
      summary += '═══════════════════════════════════════════════════════════════════════════════\n\n';

      const failuresByVault = {};
      this.failedItems.forEach(item => {
        (failuresByVault[item.vaultId] ??= { vaultName: item.vaultName, items: [] }).items.push(item);
      });

      Object.entries(failuresByVault).forEach(([vaultId, data]) => {
        summary += `VAULT: ${data.vaultName}\nUUID:  ${vaultId}\nFailed Items: ${data.items.length}\n`;
        summary += '─'.repeat(79) + '\n\n';
        data.items.forEach((item, index) => {
          summary += `  ${index + 1}. Item: "${item.itemTitle}"\n     UUID:  ${item.itemId}\n     Error: ${item.error}\n     Time:  ${item.timestamp}\n\n`;
        });
        summary += '\n';
      });
    }

    summary += '═══════════════════════════════════════════════════════════════════════════════\n';
    return summary;
  }

  getVaultStatsSummary() {
    if (Object.keys(this.vaultSummaries).length === 0) return '';

    let summary = '\n';
    summary += '═══════════════════════════════════════════════════════════════════════════════\n';
    summary += 'VAULT MIGRATION STATISTICS\n';
    summary += '═══════════════════════════════════════════════════════════════════════════════\n\n';

    Object.entries(this.vaultSummaries).forEach(([vaultId, stats]) => {
      const status = stats.failureCount === 0 && stats.sourceItemCount === stats.destItemCount ? '✓' : '⚠';
      summary += `${status} VAULT: ${stats.vaultName}\n`;
      summary += `  UUID:        ${vaultId}\n  Source:      ${stats.sourceItemCount} items\n`;
      summary += `  Destination: ${stats.destItemCount} items\n  Success:     ${stats.successCount} items\n`;
      summary += `  Failed:      ${stats.failureCount} items\n  Completed:   ${stats.timestamp}\n\n`;
    });

    summary += '═══════════════════════════════════════════════════════════════════════════════\n';
    return summary;
  }

  clear() {
    fs.ftruncateSync(this.fd, 0);
    this.resetCounters();
  }
}

const logger = new LogManager();
app.set('views', path.join(__dirname, 'views'));
app.set('view engine', 'ejs');
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.json());

// Block requests that come from other websites.
app.use((req, res, next) => {
  if (req.get('sec-fetch-site') === 'cross-site') {
    return res.status(403).json({ success: false, error: 'Cross-site requests are not allowed' });
  }
  const origin = req.get('origin');
  if (origin) {
    let originHost = null;
    try { originHost = new URL(origin).host; } catch {  }
    if (originHost !== req.get('host')) {
      return res.status(403).json({ success: false, error: 'Cross-origin requests are not allowed' });
    }
  }
  next();
});
process.on('uncaughtException', (error) => {
  logger.error(null, `Uncaught Exception: ${error.message}`);
  console.error('Uncaught Exception:', error);
});

process.on('unhandledRejection', (reason, promise) => {
  logger.error(null, `Unhandled Rejection: ${reason}`);
  console.error('Unhandled Rejection at:', promise, 'reason:', reason);
});


function sanitizeItemForLog(item) {
  return redactItemForLog(item);
}
function formatErrorForLog(error) {
  if (typeof error === 'string') return error;
  const parts = [`message: ${error.message}`];
  if (error.code) parts.push(`code: ${error.code}`);
  if (error.status) parts.push(`status: ${error.status}`);
  if (error.statusCode) parts.push(`statusCode: ${error.statusCode}`);
  if (error.details) parts.push(`details: ${JSON.stringify(error.details)}`);
  if (error.cause) parts.push(`cause: ${error.cause}`);

  const extras = Object.keys(error).filter(k => !['message', 'stack', 'code', 'status', 'statusCode', 'details', 'cause'].includes(k));
  if (extras.length > 0) {
    const extraObj = {};
    extras.forEach(k => { extraObj[k] = error[k]; });
    parts.push(`extra: ${JSON.stringify(extraObj)}`);
  }
  return parts.join(' | ');
}

function sanitizeSectionId(id) {
  if (!id || id === "") return "";
  const sanitized = id.replace(/[^a-zA-Z0-9\-_. ]/g, '');
  return sanitized || ("section-" + id.length);
}

let DEBUG_ENABLED = process.env.MIGRATION_DEBUG === '1' || process.env.MIGRATION_DEBUG === 'true';


function redactFieldsForLog(fields) {
  if (!fields) return [];
  const sensitiveLabels = /private.?key|secret|password|passphrase|credential|token|api.?key|ssh.?key|card.?number|ccnum|cvv|security.?code|\botp\b|totp|2fa|one.?time|\bpin\b/i;

  const sensitiveFieldIds = /^(ccnum|cvv|cardNumber|totp|otp|onetimepassword|pin)$/i;
  
  const privateKeyPattern = /^-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/;

  return fields.map(f => {
    const safe = {
      id: f.id,
      title: f.title,
      fieldType: f.fieldType,
      sectionId: f.sectionId,
    };

    const label = (f.title || f.id || '').toLowerCase();
    const fieldId = (f.id || '');
    const isConcealed = f.fieldType === sdk.ItemFieldType.Concealed
      || f.fieldType === sdk.ItemFieldType.Totp
      || f.fieldType === sdk.ItemFieldType.SshKey;
    const isSensitiveLabel = sensitiveLabels.test(label);
    const isSensitiveFieldId = sensitiveFieldIds.test(fieldId);
    const isPrivateKeyContent = typeof f.value === 'string' && privateKeyPattern.test(f.value.trim());

    if (isConcealed || isSensitiveLabel || isSensitiveFieldId || isPrivateKeyContent) {
      safe.value = '***REDACTED***';
      safe.hasValue = !!(f.value);
      safe.valueLength = (f.value || '').length;
      if (isPrivateKeyContent) safe.redactReason = 'private-key-content';
      else if (isSensitiveFieldId) safe.redactReason = 'sensitive-field-id';
      else if (isSensitiveLabel) safe.redactReason = 'sensitive-label';
      else safe.redactReason = 'concealed-type';
    } else if (f.value !== undefined) {
      safe.value = f.value;
    } else {
      safe.hasValue = !!(f.value);
      safe.valueLength = (f.value || '').length;
    }
    if (f.details && f.details.content && f.details.content.privateKey) {
      safe.detailsKeys = Object.keys(f.details);
      safe.detailsPrivateKeyPresent = true;
      safe.detailsPrivateKeyLength = f.details.content.privateKey.length;
    } else if (f.details) {
      safe.detailsKeys = Object.keys(f.details);
    }

    if (f._isReference) safe._isReference = true;
    if (f._sourceRefId) safe._sourceRefId = f._sourceRefId;
    return safe;
  });
}


function redactItemForLog(item) {
  const safe = { ...item };
  if (safe.fields) {
    safe.fields = redactFieldsForLog(safe.fields);
  }
  if (safe.document) {
    safe.document = { name: safe.document.name, content: '[BINARY]' };
  }
  if (safe.files) {
    safe.files = safe.files.map(f => ({ name: f.name, sectionId: f.sectionId, fieldId: f.fieldId, content: '[BINARY]' }));
  }
  
  if (safe.notes) {
    safe.notesPresent = true;
    safe.notesLength = safe.notes.length;
    delete safe.notes;
  }
  return safe;
}

// Only checked in desktop mode, where the 1Password app might be locked.
const APP_LOCKED_PATTERNS = [
  'app is locked',
  'vault is locked',
  'biometric',
  'authentication required',
  'user interaction required',
  'sign-in required',
  'session expired',
  'connect to 1password',
];

function errorMessage(error) {
  return String(error?.message ?? error ?? '');
}

function isAppLockedError(error) {
  if (error instanceof sdk.DesktopSessionExpiredError) return true;
  const msg = errorMessage(error).toLowerCase();
  return APP_LOCKED_PATTERNS.some(p => msg.includes(p));
}

function isRateLimitError(error) {
  if (error instanceof sdk.RateLimitExceededError) return true;
  const msg = errorMessage(error).toLowerCase();
  return msg.includes('rate limit') || msg.includes('429') || msg.includes('too many requests');
}

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function waitForUnlock(fn, firstError) {
  logger.warning(null, `1Password app appears locked ("${errorMessage(firstError)}"), waiting for unlock...`);

  const pollInterval = 5000;
  const maxWait = 5 * 60 * 1000;
  const start = Date.now();
  let lastNotice = start;

  while (Date.now() - start < maxWait) {
    await sleep(pollInterval);
    try {
      const result = await fn();
      logger.info(null, `1Password app unlocked, resuming after ${Math.round((Date.now() - start) / 1000)}s`);
      return result;
    } catch (retryErr) {
      if (!isAppLockedError(retryErr)) throw retryErr;
      if (Date.now() - lastNotice >= 30000) {
        lastNotice = Date.now();
        logger.info(null, `Still waiting for 1Password unlock... (${Math.round((Date.now() - start) / 1000)}s elapsed)`);
      }
    }
  }

  logger.error(null, `Timed out waiting for 1Password app to unlock after 5 minutes`);
  throw new Error(`1Password app locked for over 5 minutes, so the migration paused. Unlock the app and try again.`);
}

async function retryWithBackoff(fn, { waitForAppUnlock = false, retryRateLimits = true, maxRetries = 3, baseDelay = 1000 } = {}) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      if (waitForAppUnlock && isAppLockedError(error)) {
        return await waitForUnlock(fn, error);
      }

      const isRateLimit = retryRateLimits && isRateLimitError(error);
      const isDataConflict = errorMessage(error).toLowerCase().includes('data conflict');

      if (!retryRateLimits && isRateLimitError(error)) throw error;
      if ((isRateLimit || isDataConflict) && attempt < maxRetries) {
        const delay = isRateLimit
          ? 30000 * Math.pow(2, attempt - 1)
          : baseDelay * Math.pow(2, attempt - 1);
        logger.warning(null, `Retrying attempt ${attempt} after ${delay}ms due to ${errorMessage(error)}`);
        await sleep(delay);
      } else {
        throw error;
      }
    }
  }
}

async function runOpCli(args, { account = null, token = null } = {}) {
  const fullArgs = [...args];
  if (account) fullArgs.push('--account', account);
  const env = { ...process.env };
  if (token) env.OP_SERVICE_ACCOUNT_TOKEN = token;
  const { stdout } = await execFileAsync('op', fullArgs, { env, encoding: 'utf8', timeout: 120000, maxBuffer: 16 * 1024 * 1024 });
  return stdout;
}

async function runOpCliLimited(args, opAuth, limits, kind, requests = 1) {
  if (!limits) return runOpCli(args, opAuth);
  for (let attempt = 0; ; attempt++) {
    await acquire(limits, kind, { requests });
    try {
      return await runOpCli(args, opAuth);
    } catch (error) {
      if (attempt < 5 && isRateLimitError(error)) {
        await waitOutRateLimit(limits, kind, error);
        continue;
      }
      throw error;
    }
  }
}

async function mapWithConcurrency(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const index = next++;
      results[index] = await fn(items[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}

function isCustomCategory(category) {
  const catStr = String(category).toLowerCase();
  return catStr === 'custom' || catStr === 'unsupported';
}
function mapFieldType(fieldType) {
  const typeMap = {
    [sdk.ItemFieldType.Text]: sdk.ItemFieldType.Text,
    [sdk.ItemFieldType.Concealed]: sdk.ItemFieldType.Concealed,
    [sdk.ItemFieldType.Totp]: sdk.ItemFieldType.Totp,
    [sdk.ItemFieldType.Address]: sdk.ItemFieldType.Address,
    [sdk.ItemFieldType.SshKey]: sdk.ItemFieldType.SshKey,
    [sdk.ItemFieldType.Date]: sdk.ItemFieldType.Date,
    [sdk.ItemFieldType.MonthYear]: sdk.ItemFieldType.MonthYear,
    [sdk.ItemFieldType.Email]: sdk.ItemFieldType.Email,
    [sdk.ItemFieldType.Phone]: sdk.ItemFieldType.Phone,
    [sdk.ItemFieldType.Url]: sdk.ItemFieldType.Url,
    [sdk.ItemFieldType.Menu]: sdk.ItemFieldType.Menu,
    [sdk.ItemFieldType.CreditCardType]: sdk.ItemFieldType.CreditCardType,
    [sdk.ItemFieldType.CreditCardNumber]: sdk.ItemFieldType.CreditCardNumber,
    [sdk.ItemFieldType.Reference]: sdk.ItemFieldType.Reference,
  };
  return typeMap[fieldType] ?? sdk.ItemFieldType.Text;
}
function buildMigratedField(field) {
  const newField = {
    id: field.id || "unnamed",
    title: field.title || field.label || "unnamed",
    fieldType: mapFieldType(field.fieldType),
    value: field.value || ""
  };

  if (field.sectionId !== undefined) {
    newField.sectionId = field.sectionId;
  }
  if (field.fieldType === sdk.ItemFieldType.Address && field.details?.content) {
    newField.details = {
      type: "Address",
      content: {
        street: field.details.content.street || "",
        city: field.details.content.city || "",
        country: field.details.content.country || "",
        zip: field.details.content.zip || "",
        state: field.details.content.state || ""
      }
    };
    newField.value = "";
  }
  else if (field.fieldType === sdk.ItemFieldType.SshKey && field.details?.content) {
    newField.value = field.details.content.privateKey || field.value || "";
  }
  else if (field.fieldType === sdk.ItemFieldType.Totp) {
    const totpValue = field.value || field.details?.content?.totp || "";
    const isValidTotpUri = totpValue.startsWith("otpauth://totp/");
    const isPotentialTotpSeed = /^[A-Z2-7]{16,32}$/i.test(totpValue);
    if (isValidTotpUri || isPotentialTotpSeed) {
      newField.value = totpValue;
    } else {
      newField.fieldType = sdk.ItemFieldType.Text;
      newField.value = totpValue;
    }
  }
  else if (field.fieldType === sdk.ItemFieldType.Reference) {
    newField.fieldType = sdk.ItemFieldType.Reference;
    newField.value = field.value || "";
    newField._isReference = true;
    newField._sourceRefId = field.value || "";
  }

  return newField;
}

function buildCreditCardFields(fields, vaultId = null) {

  const builtInFieldIds = new Set([
    "cardholder", "type", "number", "ccnum", "cvv", "expiry", "validFrom"
  ]);

  const knownFieldIds = new Set([
    "cardholder", "type", "number", "ccnum", "cvv", "expiry", "validFrom",
    "bank", "phoneLocal", "phoneTollFree", "phoneIntl", "website",
    "pin", "creditLimit", "cashLimit", "interest", "issuenumber"
  ]);

  const builtInFields = [];
  const sectionFields = [];

  for (const field of fields) {
    const fieldId = field.id || "unnamed";
    const newField = {
      id: fieldId,
      title: field.title || field.label || "unnamed",
      fieldType: field.fieldType || sdk.ItemFieldType.Text,
      value: field.value || "",
    };

    const titleLower = (field.title || '').toLowerCase();

    if (field.fieldType === 'Unsupported' || field.fieldType === sdk.ItemFieldType.Unsupported) {
      if (fieldId === 'expiry' || fieldId === 'validFrom') {
        newField.fieldType = sdk.ItemFieldType.MonthYear;
      } else {
        newField.fieldType = sdk.ItemFieldType.Text;
      }
    }

    if (fieldId === "type" || titleLower === "type") {
      newField.fieldType = sdk.ItemFieldType.CreditCardType;
      const cardTypeMap = {
        "mc": "Mastercard", "mastercard": "Mastercard",
        "visa": "Visa",
        "amex": "American Express", "american express": "American Express",
        "discover": "Discover",
        "diners club": "Diners Club", "dinersclub": "Diners Club",
        "jcb": "JCB",
        "unionpay": "UnionPay",
      };
      const mapped = cardTypeMap[(field.value || '').toLowerCase()];
      newField.value = mapped || field.value || "";
    }
    if (fieldId === "expiry" || fieldId === "validFrom" || titleLower.includes("expiry") || titleLower.includes("expiration")) {
      newField.fieldType = sdk.ItemFieldType.MonthYear;
      const v = (field.value || "").trim();
      if (/^\d{2}\/\d{4}$/.test(v)) {
        newField.value = v;
      } else if (/^\d{2}-\d{4}$/.test(v)) {
        newField.value = v.replace('-', '/');
      } else if (/^\d{4}$/.test(v)) {
        newField.value = `${v.slice(0, 2)}/20${v.slice(2)}`;
      } else if (/^\d{2}\/\d{2}$/.test(v)) {
        newField.value = `${v.slice(0, 2)}/20${v.slice(3)}`;
      } else if (/^\d{6}$/.test(v)) {
        newField.value = `${v.slice(4, 6)}/${v.slice(0, 4)}`;
      } else if (v === "") {
        newField.value = "";
      } else {
        newField.value = v;
      }
    }

    if (fieldId === "number" || fieldId === "ccnum") {
      newField.fieldType = sdk.ItemFieldType.CreditCardNumber;
    }

    if (fieldId === "cvv" || titleLower.includes("verification")) {
      newField.fieldType = sdk.ItemFieldType.Concealed;
    }

    if (fieldId === "pin" || titleLower === "pin") {
      newField.fieldType = sdk.ItemFieldType.Concealed;
    }

    if (builtInFieldIds.has(fieldId)) {
      newField.sectionId = "";
      builtInFields.push(newField);
    } else {
      const sourceSectionId = field.sectionId;
      if (sourceSectionId && sourceSectionId !== "" && sourceSectionId !== null) {
        newField.sectionId = sourceSectionId;
      } else if (knownFieldIds.has(fieldId)) {
        newField.sectionId = "";
      } else {
        newField.sectionId = "add more";
      }
      sectionFields.push(newField);
    }
  }

  const result = [...builtInFields, ...sectionFields];

  return result;
}

function buildCustomAsLogin(item, vaultId) {
  logger.info(vaultId, `Converting CUSTOM item "${item.title}" to Login category (preserving concealed fields)`);

  const newItem = {
    title: item.title,
    category: sdk.ItemCategory.Login,
    vaultId: null,
  };

  if (item.notes && item.notes.trim() !== "") {
    newItem.notes = item.notes;
  }

  if (item.fields && item.fields.length > 0) {

    const builtInFields = [];
    const sectionFields = [];

    for (const field of item.fields) {
      const label = (field.title || field.label || '').toLowerCase();
      const fieldType = field.fieldType;
      const fieldId = (field.id || '').toLowerCase();

      if (fieldId === 'username' || label === 'username' || label === 'user' ||
          label === 'email address' || label === 'login') {
        builtInFields.push({
          id: "username",
          title: field.title || field.label || "username",
          fieldType: sdk.ItemFieldType.Text,
          value: field.value || "",
        });
        continue;
      }

      if (fieldId === 'password' || label === 'password' || label === 'pass' ||
          (fieldType === sdk.ItemFieldType.Concealed && label.includes('password'))) {
        builtInFields.push({
          id: "password",
          title: field.title || field.label || "password",
          fieldType: sdk.ItemFieldType.Concealed,
          value: field.value || "",
        });
        continue;
      }

      if (fieldType === sdk.ItemFieldType.Totp || label === 'otp' ||
          label === 'one-time password' || label === 'totp' ||
          fieldId === 'totp' || fieldId === 'otp') {
        const totpValue = field.value || field.details?.content?.totp || "";
        builtInFields.push({
          id: "onetimepassword",
          title: field.title || field.label || "one-time password",
          fieldType: sdk.ItemFieldType.Totp,
          value: totpValue,
        });
        continue;
      }

      const mapped = buildMigratedField(field);
      if (fieldType === sdk.ItemFieldType.Concealed) {
        mapped.fieldType = sdk.ItemFieldType.Concealed;
      }
      if (mapped.sectionId === undefined) {
        mapped.sectionId = "additional";
      }
      sectionFields.push(mapped);
    }

    newItem.fields = [...builtInFields, ...sectionFields];
  }

  if (item.sections && item.sections.length > 0) {
    newItem.sections = item.sections.map(section => ({
      id: section.id,
      title: section.title || section.label || ""
    }));
  }

  if (newItem.fields?.some(f => f.sectionId === "additional")) {
    if (!newItem.sections) newItem.sections = [];
    if (!newItem.sections.some(s => s.id === "additional")) {
      newItem.sections.push({ id: "additional", title: "Additional Details" });
    }
  }

  if (item.files && item.files.length > 0) {
    newItem.files = [];
    const fileSectionIds = new Set();
    for (const [index, file] of item.files.entries()) {
      try {
        const fileName = file.name;
        const fileContent = file.content;
        const fileSectionId = file.sectionId || "add more";
        const fileFieldId = file.fieldId || `${fileName}-${Date.now()}-${index}`;
        if (fileName && fileContent) {
          newItem.files.push({
            name: fileName,
            content: fileContent instanceof Uint8Array ? fileContent : new Uint8Array(fileContent),
            sectionId: fileSectionId,
            fieldId: fileFieldId
          });
          fileSectionIds.add(fileSectionId);
        }
      } catch (fileError) {
        logger.warning(vaultId, `File processing failed for ${item.title}: ${fileError.message}`);
      }
    }
    if (!newItem.sections) newItem.sections = [];
    for (const sectionId of fileSectionIds) {
      if (!newItem.sections.some(s => s.id === sectionId)) {
        newItem.sections.push({ id: sectionId, title: sectionId === "add more" ? "" : sectionId });
      }
    }
  }

  newItem.tags = item.tags && item.tags.length > 0 ? [...item.tags, 'migrated'] : ['migrated'];

  if (item.websites && item.websites.length > 0) {
    newItem.websites = item.websites.map(website => ({
      url: website.url || website.href || "",
      label: website.label || "website",
      autofillBehavior: website.autofillBehavior || sdk.AutofillBehavior.AnywhereOnWebsite
    }));
  }

  return newItem;
}


function buildNewItem(item, newVaultId, vaultId) {

  if (isCustomCategory(item.category)) {
    const newItem = buildCustomAsLogin(item, vaultId);
    newItem.vaultId = newVaultId;
    return newItem;
  }

  const newItem = {
    title: item.title,
    category: item.category || sdk.ItemCategory.Login,
    vaultId: newVaultId
  };

  if (item.notes && item.notes.trim() !== "") {
    newItem.notes = item.notes;
  } else if (item.category === sdk.ItemCategory.SecureNote) {
    newItem.notes = "Migrated Secure Note";
  }
  if (item.category === 'SSH_KEY') {
    newItem.category = sdk.ItemCategory.SshKey;
  }

  if (item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard) {
    newItem.category = sdk.ItemCategory.CreditCard;
    if (item.fields && item.fields.length > 0) {
      newItem.fields = buildCreditCardFields(item.fields, vaultId);
    }

    newItem.sections = [
      { id: "", title: "" }
    ];

    if (item.sections && item.sections.length > 0) {
      for (const section of item.sections) {
        if (section.id && section.id !== "" && section.id !== null) {
          newItem.sections.push({
            id: section.id,
            title: section.title || section.label || ""
          });
        }
      }
    }

    if (newItem.fields) {
      for (const field of newItem.fields) {
        const sid = field.sectionId;
        if (sid && sid !== "" && sid !== null) {
          if (!newItem.sections.some(s => s.id === sid)) {
            newItem.sections.push({ id: sid, title: sid === "add more" ? "" : sid });
          }
        }
      }
    }
  }
  
  else if (item.category === 'Database' || item.category === sdk.ItemCategory.Database) {
    newItem.category = sdk.ItemCategory.Database;

    const dbBuiltInFieldIds = new Set([
      "database_type", "hostname", "port", "database",
      "username", "password", "sid", "alias", "options"
    ]);

    if (item.fields && item.fields.length > 0) {
      const builtInFields = [];
      const sectionFields = [];

      const sectionIdRemap = {};
      if (item.sections) {
        for (const s of item.sections) {
          if (s.id && s.id !== "") {
            const sanitized = sanitizeSectionId(s.id);
            if (sanitized !== s.id) {
              sectionIdRemap[s.id] = sanitized;
            }
          }
        }
      }

      for (const field of item.fields) {
        const mapped = buildMigratedField(field);
        if (dbBuiltInFieldIds.has(field.id)) {
          mapped.sectionId = "";
          builtInFields.push(mapped);
        } else {
          if (!mapped.sectionId || mapped.sectionId === undefined) {
            mapped.sectionId = "add more";
          } else if (sectionIdRemap[mapped.sectionId]) {
            mapped.sectionId = sectionIdRemap[mapped.sectionId];
          }
          sectionFields.push(mapped);
        }
      }

      newItem.fields = [...builtInFields, ...sectionFields];
    }

    const referencedSectionIds = new Set();
    if (newItem.fields) {
      for (const field of newItem.fields) {
        if (field.sectionId && field.sectionId !== "" && field.sectionId !== null) {
          referencedSectionIds.add(field.sectionId);
        }
      }
    }

    const sectionIdRemap = {};
    const sourceSectionMap = {};
    if (item.sections) {
      for (const s of item.sections) {
        if (s.id && s.id !== "") {
          sourceSectionMap[s.id] = s;
          const sanitized = sanitizeSectionId(s.id);
          if (sanitized !== s.id) {
            sourceSectionMap[sanitized] = s;
          }
        }
      }
    }

    newItem.sections = [{ id: "", title: "" }];

    for (const sid of referencedSectionIds) {
      const sourceSection = sourceSectionMap[sid];
      newItem.sections.push({
        id: sid,
        title: sourceSection ? (sourceSection.title || sourceSection.label || "") : (sid === "add more" ? "" : "")
      });
    }
  }
  
  else if (item.fields && item.fields.length > 0) {
    newItem.fields = item.fields.map(buildMigratedField);
  }

  else if (item.category === sdk.ItemCategory.SecureNote) {
    newItem.notes = item.notes || "Migrated Secure Note";
  }

  if (!(item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard ||
        item.category === 'Database' || item.category === sdk.ItemCategory.Database)) {
    if (item.sections && item.sections.length > 0) {
      newItem.sections = item.sections.map(section => ({
        id: section.id,
        title: section.title || section.label || ""
      }));
    }
  }

  if (item.files && item.files.length > 0) {
    newItem.files = [];
    const fileSectionIds = new Set();

    for (const [index, file] of item.files.entries()) {
      try {
        const fileName = file.name;
        const fileContent = file.content;
        const fileSectionId = file.sectionId || "add more";
        const fileFieldId = file.fieldId || `${fileName}-${Date.now()}-${index}`;

        if (fileName && fileContent) {
          newItem.files.push({
            name: fileName,
            content: fileContent instanceof Uint8Array ? fileContent : new Uint8Array(fileContent),
            sectionId: fileSectionId,
            fieldId: fileFieldId
          });
          fileSectionIds.add(fileSectionId);
        }
      } catch (fileError) {
        logger.warning(vaultId, `File processing failed for ${item.title}: ${fileError.message}`);
      }
    }

    if (!newItem.sections) newItem.sections = [];
    for (const sectionId of fileSectionIds) {
      if (!newItem.sections.some(section => section.id === sectionId)) {
        newItem.sections.push({ id: sectionId, title: sectionId === "add more" ? "" : sectionId });
      }
    }
  }

  newItem.tags = item.tags && item.tags.length > 0 ? [...item.tags, 'migrated'] : ['migrated'];

  if (item.websites && item.websites.length > 0) {
    newItem.websites = item.websites.map(website => ({
      url: website.url || website.href || "",
      label: website.label || "website",
      autofillBehavior: website.autofillBehavior || sdk.AutofillBehavior.AnywhereOnWebsite
    }));
  }

  return newItem;
}

app.get('/', (req, res) => {
  res.render('welcome', { currentPage: 'welcome' });
});

app.get('/migration', (req, res) => {
  res.render('migration', { error: null, currentPage: 'migration' });
});


app.get('/migration/env-status', (req, res) => {
  res.json({
    loaded: envConfig.loaded,
    authMode: envConfig.authMode,
    hasSourceToken: !!envConfig.sourceToken,
    hasDestToken: !!envConfig.destToken,
    hasSourceAccount: !!envConfig.sourceAccount,
    hasDestAccount: !!envConfig.destAccount,
    hasBothTokens: !!(envConfig.sourceToken && envConfig.destToken),
    hasBothAccounts: !!(envConfig.sourceAccount && envConfig.destAccount),
    ready: envConfig.authMode === 'service-account'
      ? !!(envConfig.sourceToken && envConfig.destToken)
      : envConfig.authMode === 'desktop'
        ? !!(envConfig.sourceAccount && envConfig.destAccount)
        : false,
  });
});
app.post('/migration/env-reload', (req, res) => {
  logger.info(null, 'Reloading .env file...');
  envConfig = { loaded: false, authMode: null, sourceToken: null, destToken: null, sourceAccount: null, destAccount: null };
  loadEnvFile();
  const ready = envConfig.authMode === 'service-account'
    ? !!(envConfig.sourceToken && envConfig.destToken)
    : envConfig.authMode === 'desktop'
      ? !!(envConfig.sourceAccount && envConfig.destAccount)
      : false;
  logger.info(null, `Env reload complete. Loaded: ${envConfig.loaded}, mode: ${envConfig.authMode || 'none'}, ready: ${ready}`);
  res.json({ success: true, loaded: envConfig.loaded, authMode: envConfig.authMode, ready });
});


const VALID_AUTH_MODES_SERVER = ['service-account', 'desktop'];

app.post('/migration/list-vaults', async (req, res) => {
  const { serviceToken, authMode, sourceAccountName, useEnvTokens } = req.body;

  let resolvedToken = serviceToken;
  let resolvedAuthMode = VALID_AUTH_MODES_SERVER.includes(authMode) ? authMode : 'service-account';
  let resolvedAccountName = typeof sourceAccountName === 'string' ? sourceAccountName : '';

  if (useEnvTokens && envConfig.loaded) {
    resolvedAuthMode = envConfig.authMode || 'service-account';
    if (resolvedAuthMode === 'desktop') {
      resolvedAccountName = envConfig.sourceAccount;
      if (!resolvedAccountName) {
        return res.status(400).json({ success: false, error: 'SOURCE_ACCOUNT not found in .env' });
      }
    } else {
      resolvedToken = envConfig.sourceToken;
      if (!resolvedToken) {
        return res.status(400).json({ success: false, error: 'SOURCE_TOKEN not found in .env' });
      }
    }
  } else if (resolvedAuthMode === 'desktop') {
    if (!resolvedAccountName) {
      return res.status(400).json({ success: false, error: 'Source account name is required for desktop auth' });
    }
  } else {
    if (!resolvedToken) {
      return res.status(400).json({ success: false, error: 'Service token is required' });
    }
  }

  try {
    logger.info(null, `Listing vaults for source tenant (mode: ${resolvedAuthMode}${useEnvTokens ? ', from .env' : ''})`);

    const sdkInstance = resolvedAuthMode === 'desktop'
      ? new OnePasswordSDK({ authMode: 'desktop', accountName: resolvedAccountName })
      : new OnePasswordSDK({ token: resolvedToken });
    await sdkInstance.initializeClient();
    const vaults = await sdkInstance.listVaults();

    const vaultsWithCounts = await mapWithConcurrency(vaults, 10, async ({ activeItemCount, ...vault }) => {
      // vaults.list already includes item counts, so there's no need to list each vault.
      const count = typeof activeItemCount === 'number'
        ? activeItemCount
        : await getVaultItemCount(vault.id, sdkInstance, { skipArchived: true });
      logger.info(vault.id, `Vault ${vault.name}: ${count} items (type: ${vault.vaultType})`);
      return { ...vault, itemCount: count };
    });

    res.json({ success: true, vaults: vaultsWithCounts });
  } catch (error) {
    logger.error(null, `Failed to list vaults: ${error.message}`);
    res.status(500).json({ success: false, error: error.message });
  }
});

let isMigrationCancelled = false;
const activeMigrations = new Map();

// What a page needs to show a migration, kept on the server so a refreshed (or reopened) page can pick
// up a running migration again. It holds the latest event of each kind (each vault's status, the overall
// status, rate limit state), not the whole history, and never the tokens.
const FINISHED_FEED_TTL = 15 * 60 * 1000;
const migrationFeeds = new Map();

class MigrationFeed {
  constructor(id, info) {
    this.id = id;
    this.info = { ...info, startedAt: Date.now() };
    this.latest = new Map();
    this.clients = new Set();
    this.finished = null;
    this.resultSeen = false;
  }

  static keyFor(payload) {
    if (payload.finished) return 'finished';
    if (payload.rateLimitEvent === 'usage') return `usage:${payload.usage?.label ?? ''}`;
    if (payload.rateLimitEvent) return 'pause';
    if (payload.outcome?.vaultId) return `vault:${payload.outcome.vaultId}`;
    return 'status';
  }

  publish(payload) {
    const key = MigrationFeed.keyFor(payload);
    this.latest.delete(key);
    this.latest.set(key, payload);
    if (payload.finished) {
      this.finished = Date.now();
      if (this.clients.size > 0) this.resultSeen = true;
    }
    for (const res of this.clients) MigrationFeed.write(res, payload);
  }

  static write(res, payload) {
    try { res.write(`data: ${JSON.stringify(payload)}\n\n`); } catch { /* the close handler tidies up */ }
  }

  // replay: send the current state first (for a page that is catching up)
  attach(res, { replay = false, onEmpty = () => {} } = {}) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();
    if (replay) {
      MigrationFeed.write(res, { attached: this.summary() });
      for (const payload of this.latest.values()) MigrationFeed.write(res, payload);
      if (this.finished) {
        this.resultSeen = true;
        res.end();
        return;
      }
    }
    this.clients.add(res);
    const keepAlive = setInterval(() => { try { res.write(': keep-alive\n\n'); } catch { } }, 15000);
    res.on('close', () => {
      clearInterval(keepAlive);
      this.clients.delete(res);
      if (this.clients.size === 0 && !this.finished) onEmpty();
    });
  }

  end() {
    for (const res of this.clients) { try { res.end(); } catch { } }
    this.clients.clear();
    setTimeout(() => migrationFeeds.delete(this.id), FINISHED_FEED_TTL).unref?.();
  }

  summary() {
    return { id: this.id, ...this.info, running: !this.finished };
  }
}

// The migration a page should show when it loads: one that's running, or one that finished while no
// page was watching (so its result isn't lost).
function currentFeed() {
  const feeds = [...migrationFeeds.values()].sort((a, b) => b.info.startedAt - a.info.startedAt);
  return feeds.find(f => !f.finished) || feeds.find(f => !f.resultSeen) || null;
}

app.get('/migration/active', (req, res) => {
  const feed = currentFeed();
  res.json({ success: true, migration: feed ? feed.summary() : null });
});

app.get('/migration/watch', (req, res) => {
  const feed = migrationFeeds.get(String(req.query.id || ''));
  if (!feed) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.flushHeaders();
    res.write(`data: ${JSON.stringify({ success: false, message: 'That migration is no longer available', finished: true, gone: true })}\n\n`);
    return res.end();
  }
  activeMigrations.get(feed.id)?.clientReconnected();
  feed.attach(res, { replay: true, onEmpty: () => activeMigrations.get(feed.id)?.clientDisconnected() });
});

app.post('/migration/cancel', (req, res) => {
  isMigrationCancelled = true;
  for (const control of activeMigrations.values()) control.cancel();
  logger.info(null, 'Migration cancellation requested');
  res.json({ success: true, message: 'Migration cancellation requested' });
});

app.post('/migration/resume', (req, res) => {
  const control = activeMigrations.get(String(req.body?.migrationId || ''));
  if (!control) return res.status(404).json({ success: false, error: 'No running migration with that id' });
  const wasPaused = control.resume();
  res.json({ success: true, wasPaused });
});

function rateLimitMonitorFor(token, label) {
  return RateLimitMonitor.for(token, label, { runOp: runOpCli, log: logger });
}

// Worst case is one write per item, best case one per batch.
function estimateWrites(vaultItemCounts) {
  let perItem = 0;
  let perBatch = 0;
  for (const count of vaultItemCounts) {
    const refs = Math.ceil(count * 0.05);
    perItem += 2 + count + refs;
    perBatch += 2 + Math.ceil(count / BATCH_SIZE) + Math.ceil(count * 0.1) + refs;
  }
  return { perItem, perBatch };
}

app.post('/migration/rate-limit-check', async (req, res) => {
  const { vaultItemCounts, authMode, useEnv, destToken } = req.body || {};
  if (!Array.isArray(vaultItemCounts)) {
    return res.json({ success: false, error: 'vaultItemCounts array required' });
  }
  const useEnvConfig = (useEnv === true || useEnv === 'true') && envConfig.loaded;
  const mode = useEnvConfig ? (envConfig.authMode || 'service-account') : authMode;
  const token = useEnvConfig ? envConfig.destToken : destToken;
  if (mode === 'desktop' || typeof token !== 'string' || !token) {
    return res.json({ success: true, supported: false });
  }

  const counts = vaultItemCounts.map(n => typeof n === 'number' && isFinite(n) ? Math.max(0, Math.floor(n)) : 0);
  const monitor = rateLimitMonitorFor(token, 'destination');
  await monitor.exclusive(() => monitor.refresh());
  const limiting = monitor.limiting('write');
  if (!limiting) return res.json({ success: true, supported: false });

  const estimate = estimateWrites(counts);
  const estimatedWrites = monitor.countsPerItem.write === false ? estimate.perBatch : estimate.perItem;
  const available = Math.max(0, limiting.available - monitor.reserve('write'));
  logger.info(null, `Rate limit check: destination has ${available} writes available (${limiting.scope} limit ${limiting.limit}), migration needs up to ${estimatedWrites}`);
  res.json({
    success: true,
    supported: true,
    usage: monitor.snapshot(),
    available,
    estimatedWrites,
    estimatedWritesIfBatched: estimate.perBatch,
    willPause: estimatedWrites > available,
    limitingScope: limiting.scope,
    limit: limiting.limit,
    resetAt: limiting.resetAt,
  });
});

async function getVaultItemCount(vaultId, sdkInstanceOrToken, { skipArchived = false } = {}) {
  try {
    let sdkInstance;
    if (typeof sdkInstanceOrToken === 'string') {
      sdkInstance = new OnePasswordSDK({ token: sdkInstanceOrToken });
      await sdkInstance.initializeClient();
    } else {
      sdkInstance = sdkInstanceOrToken;
      if (!sdkInstance.client) await sdkInstance.initializeClient();
    }
    const activeItems = await sdkInstance.retry(() => sdkInstance.client.items.list(vaultId));
    const activeCount = activeItems.length;

    if (!skipArchived) {
      try {
        const archivedItems = await sdkInstance.retry(() => sdkInstance.client.items.list(vaultId, {
          type: "ByState",
          content: { active: false, archived: true }
        }));
        if (archivedItems.length > 0) {
          logger.info(vaultId, `Contains ${archivedItems.length} archived items`);
        }
      } catch (archiveError) {
        logger.warning(vaultId, `Could not fetch archived items: ${archiveError.message}`);
      }
    }

    return activeCount;
  } catch (error) {
    if (error instanceof MigrationCancelledError) throw error;
    logger.error(vaultId, `Error fetching item count: ${error.message}`);
    return 0;
  }
}

const BATCH_SIZE = 100;
// A batch also closes once its attachments and documents add up to this many bytes (1 GB, room for
// 20 of the SDK's largest 50 MB files), so a failed batch never has too much to send again. An item
// bigger than this on its own is created by itself.
const BATCH_MAX_BYTES = Math.max(1, Number(process.env.MIGRATION_BATCH_MAX_BYTES) || 1024 * 1024 * 1024);
const BATCH_GET_SIZE = 50;
const READ_CONCURRENCY = Math.max(1, Number(process.env.MIGRATION_READ_CONCURRENCY) || 6);
const FILES_PER_ITEM_CONCURRENCY = 4;

function isCreditCardItem(item) {
  return item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard;
}

function isDocumentItem(item) {
  return item.category === 'Document' || item.category === sdk.ItemCategory.Document;
}

function destVaultNameFor(vaultName, suffix) {
  return suffix ? `${vaultName} (Migrated - ${suffix})` : `${vaultName} (Migrated)`;
}

async function completeSourceItems(vaultId, items, sourceSDK, opAuth) {
  for (const item of items) {
    if (isDocumentItem(item) && !item.document) {
      try {
        const fullItem = await sourceSDK.retry(() => sourceSDK.client.items.get(vaultId, item.id));
        if (fullItem.category === sdk.ItemCategory.Document && fullItem.document) {
          const documentContent = await sourceSDK.retry(() =>
            sourceSDK.client.items.files.read(vaultId, item.id, fullItem.document)
          );
          item.document = {
            name: fullItem.document.name,
            content: documentContent instanceof Uint8Array ? documentContent : new Uint8Array(documentContent)
          };
        }
      } catch (docError) {
        if (docError instanceof MigrationCancelledError) throw docError;
        logger.warning(vaultId, `Document handling failed for ${item.title}: ${docError.message}`);
      }
    }

    if (isCreditCardItem(item)) {
      const expiryField = item.fields?.find(f => f.id === 'expiry');
      if (expiryField && (!expiryField.value || expiryField.fieldType === 'Unsupported')) {
        try {
          // The SDK can't read card expiry dates, but the CLI can.
          const cliOutput = await runOpCliLimited(['item', 'get', item.id, '--vault', vaultId, '--format', 'json'], opAuth, sourceSDK.limits, 'read', 2);
          const cliItem = JSON.parse(cliOutput);
          const cliExpiryField = cliItem.fields?.find(f => f.id === 'expiry');
          if (cliExpiryField && cliExpiryField.value) {
            expiryField.value = cliExpiryField.value;
            expiryField.fieldType = sdk.ItemFieldType.MonthYear;
            logger.info(vaultId, `Recovered expiry date via CLI: ${cliExpiryField.value}`);
          } else {
            logger.warning(vaultId, `CLI also returned no expiry value for "${item.title}"`);
          }
        } catch (cliError) {
          if (cliError instanceof MigrationCancelledError) throw cliError;
          logger.warning(vaultId, `CLI fallback for expiry failed: ${cliError.message}`);
        }
      }
    }
  }
}

// onProgress(itemsRead, totalItems) is called as items (and their attachments) finish reading.
async function readSourceVault(vaultId, sourceSDK, opAuth, onProgress = null) {
  const { items, sourceItemCount } = await sourceSDK.listVaultItems(vaultId, onProgress);
  await completeSourceItems(vaultId, items, sourceSDK, opAuth);
  return { items, sourceItemCount };
}

async function desktopReadAllVaults(sourceSDK, vaultsToRead, sourceAccountName, isCancelled, onProgress = null) {
  const vaultData = [];

  for (const [index, vault] of vaultsToRead.entries()) {
    if (isCancelled()) break;
    if (onProgress) onProgress(index, 0, null);

    logger.info(vault.id, `[Desktop Phase 1] Reading vault "${vault.name}"`);
    const base = { vaultId: vault.id, vaultName: vault.name, vaultType: vault.vaultType || 'shared', suffix: vault.suffix || '' };

    try {
      const { items, sourceItemCount } = await readSourceVault(vault.id, sourceSDK, { account: sourceAccountName },
        onProgress ? (done, total) => onProgress(index, done, total) : null);
      logger.info(vault.id, `[Desktop Phase 1] Read ${items.length} items from "${vault.name}"`);
      vaultData.push({ ...base, items, sourceItemCount });
    } catch (error) {
      logger.error(vault.id, `[Desktop Phase 1] Failed to read vault "${vault.name}": ${error.message}`);
      logger.logFailedVault(vault.id, vault.name, error);
      vaultData.push({ ...base, items: [], sourceItemCount: 0, error: error.message });
    }
  }

  return vaultData;
}

async function findDestPrivateVault(vaultId, destSDK) {
  if (destSDK.privateVaultId) return destSDK.privateVaultId;
  destSDK.privateVaultId = await lookUpDestPrivateVault(vaultId, destSDK);
  return destSDK.privateVaultId;
}

async function lookUpDestPrivateVault(vaultId, destSDK) {
  logger.info(vaultId, `Personal vault, looking for the existing Private vault on destination`);
  try {
    const destVaults = await destSDK.listVaults();
    const privateVault = destVaults.find(v => v.vaultType === 'personal');
    if (privateVault) {
      logger.info(vaultId, `Found destination Private vault: "${privateVault.name}" [${privateVault.id}]`);
      return privateVault.id;
    }
    const byName = destVaults.find(v => {
      const n = (v.name || '').toLowerCase();
      return n === 'private' || n === 'employee' || n.includes('employee vault');
    });
    if (byName) {
      logger.info(vaultId, `Found destination Private vault by name: "${byName.name}" [${byName.id}]`);
      return byName.id;
    }
    throw new Error('Could not find a Private/Employee vault on the destination account');
  } catch (error) {
    logger.error(vaultId, `Failed to find destination Private vault: ${error.message}`);
    throw new Error(`Could not find destination Private vault: ${error.message}`);
  }
}

const SDK_CANT_CREATE_VAULTS = /not (yet )?(supported|implemented)|unsupported|unknown (method|function)|is not a function/i;

// Creates the vault with the SDK. The CLI is only a backup if the SDK can't do it.
async function createDestVault(vaultId, vaultName, suffix, destSDK, opAuth) {
  const destVaultName = destVaultNameFor(vaultName, suffix);
  try {
    let newVaultId;
    try {
      const vault = await destSDK.retry(
        () => destSDK.client.vaults.create({ title: destVaultName, allowAdminsAccess: true }),
        { kind: 'write' }
      );
      newVaultId = vault.id;
    } catch (sdkError) {
      if (sdkError instanceof MigrationCancelledError || !SDK_CANT_CREATE_VAULTS.test(errorMessage(sdkError))) throw sdkError;
      logger.warning(vaultId, `SDK could not create the vault (${errorMessage(sdkError)}), using the op CLI instead`);
      const cliOutput = await runOpCliLimited(['vault', 'create', destVaultName, '--format', 'json'], opAuth, destSDK.limits, 'write', 2);
      newVaultId = JSON.parse(cliOutput).id;
    }
    logger.info(vaultId, `Created destination vault "${destVaultName}" [${newVaultId}]`);
    return newVaultId;
  } catch (error) {
    if (error instanceof MigrationCancelledError) throw error;
    logger.error(vaultId, `Failed to create destination vault: ${error.message}`);
    throw new Error(`Vault creation failed: ${error.message}`);
  }
}

// Bytes of file and document content an item will upload.
function binaryBytes(newItem) {
  const size = (content) => (content && content.length) || 0;
  return (newItem.files || []).reduce((total, f) => total + size(f.content), 0)
    + (newItem.document ? size(newItem.document.content) : 0);
}

// How many items from `start` fit in one batch: at most `max`, and at most BATCH_MAX_BYTES of
// attachments (always at least one, since anything bigger was set aside to go on its own).
function itemsWithinBudget(entries, start, max) {
  let count = 0;
  let bytes = 0;
  while (count < max && start + count < entries.length) {
    const next = entries[start + count].bytes || 0;
    if (count > 0 && bytes + next > BATCH_MAX_BYTES) break;
    bytes += next;
    count++;
  }
  return Math.max(1, count);
}

// The SDK sends a batch as one request and says nothing until 1Password answers, so the progress
// bar would sit still for the whole batch. While a batch is out, this moves the bar at the speed
// earlier batches went, stopping short of the end, and the real count takes over when it returns.
// Starting guess: ~110 ms an item (measured on a real account) plus upload time for attachments.
const ESTIMATE_MS_PER_ITEM = 110;
const ESTIMATE_MS_PER_MB = 800;
const ESTIMATE_CAP = 0.9;

function batchEstimator(destSDK) {
  destSDK.writeSpeed ??= { factor: 1, measured: false };
  const speed = destSDK.writeSpeed;
  const baseMs = (chunk) => 300 + chunk.length * ESTIMATE_MS_PER_ITEM
    + chunk.reduce((n, e) => n + (e.bytes || 0), 0) / 1048576 * ESTIMATE_MS_PER_MB;

  return {
    // Calls report(estimatedItemsDone, secondsElapsed) a few times a second until stopped.
    start(chunk, report) {
      const startedAt = Date.now();
      const expected = baseMs(chunk) * speed.factor;
      const tick = () => {
        const elapsed = Date.now() - startedAt;
        // up to ESTIMATE_CAP by the expected time, then creeping toward (never reaching) the end
        const fraction = elapsed <= expected
          ? ESTIMATE_CAP * (elapsed / expected)
          : ESTIMATE_CAP + (1 - ESTIMATE_CAP) * 0.5 * (1 - Math.exp(-(elapsed - expected) / expected));
        report(chunk.length * fraction, Math.floor(elapsed / 1000));
      };
      const timer = setInterval(tick, 400);
      return {
        stop(succeeded) {
          clearInterval(timer);
          if (!succeeded) return;
          const ratio = Math.min(10, Math.max(0.1, (Date.now() - startedAt) / baseMs(chunk)));
          speed.factor = speed.measured ? (speed.factor + ratio) / 2 : ratio;
          speed.measured = true;
        },
      };
    },
  };
}

async function writeItemsToVault({ vaultId, vaultName, items, newVaultId, destSDK, isCancelled, onProgress }) {
  let processedItems = 0;
  let successCount = 0;
  let failureCount = 0;
  const failures = [];
  const idMap = new Map();
  const itemsWithRefs = [];

  const recordFailure = (itemId, title, error) => {
    processedItems++;
    failureCount++;
    logger.logFailedItem(vaultId, vaultName, itemId, title, error);
    failures.push({ id: itemId, title, error: error.message });
  };

  const recordSuccess = (entry, createdItem, how) => {
    processedItems++;
    successCount++;
    idMap.set(entry.sourceId, createdItem.id);
    logger.info(vaultId, `${how} item [${entry.sourceId}] "${entry.sourceTitle}" → ${createdItem.id}`, { itemId: entry.sourceId });
    if (entry.refFields.length > 0) {
      itemsWithRefs.push({ sourceItemId: entry.sourceId, destItemId: createdItem.id, createdItem, refFields: entry.refFields });
    }
  };

  logger.info(vaultId, `Phase 1: Building item objects...`);

  const batchableItems = [];
  const individualItems = [];

  for (const item of items) {
    try {
      if (DEBUG_ENABLED) {
        logger.info(vaultId, `[DEBUG] Source item "${item.title}" [${item.id}], category: "${item.category}"`);
        logger.info(vaultId, `[DEBUG] Source fields (${item.fields?.length || 0}): ${JSON.stringify(redactFieldsForLog(item.fields || []))}`);
        logger.info(vaultId, `[DEBUG] Source sections (${item.sections?.length || 0}): ${JSON.stringify(item.sections || [])}`);
        logger.info(vaultId, `[DEBUG] Source websites: ${JSON.stringify(item.websites || [])}`);
        logger.info(vaultId, `[DEBUG] Source tags: ${JSON.stringify(item.tags || [])}`);
        logger.info(vaultId, `[DEBUG] Source files: ${(item.files || []).map(f => f.name).join(', ') || 'none'}`);
        logger.info(vaultId, `[DEBUG] Source notes present: ${!!(item.notes && item.notes.trim())}`);
      }

      const newItem = buildNewItem(item, newVaultId, vaultId);
      if (DEBUG_ENABLED) {
        logger.info(vaultId, `[DEBUG] Built dest item "${newItem.title}", category: "${newItem.category}"`);
        logger.info(vaultId, `[DEBUG] Full redacted payload: ${JSON.stringify(redactItemForLog(newItem))}`);
      }

      if (item.document) {
        newItem.document = item.document;
      }

      const refFields = [];
      if (newItem.fields) {
        const fieldsWithoutRefs = [];
        for (const field of newItem.fields) {
          if (field._isReference && field._sourceRefId) {
            refFields.push({ fieldId: field.id, title: field.title, sectionId: field.sectionId, sourceRefId: field._sourceRefId });
          } else {
            delete field._isReference;
            delete field._sourceRefId;
            fieldsWithoutRefs.push(field);
          }
        }
        newItem.fields = fieldsWithoutRefs;
      }

      // Attachments, documents and credit cards go in batches too: a batch counts as one write
      // against the rate limit however many items it holds.
      const bytes = binaryBytes(newItem);
      const entry = { sourceId: item.id, sourceTitle: item.title, newItem, refFields, bytes };

      if (bytes > BATCH_MAX_BYTES) {
        individualItems.push(entry);
      } else {
        batchableItems.push(entry);
      }
    } catch (error) {
      if (DEBUG_ENABLED) {
        logger.error(vaultId, `[DEBUG] Phase 1 build FAILED for "${item.title}" [${item.id}]: ${formatErrorForLog(error)}`);
      }
      recordFailure(item.id, item.title, error);
    }
  }

  const cancelledResult = () => ({ cancelled: true, successCount, failureCount, failures });

  const estimator = batchEstimator(destSDK);
  logger.info(vaultId, `Phase 2: Creating items (${batchableItems.length} in batches, ${individualItems.length} one at a time because they're over ${Math.round(BATCH_MAX_BYTES / 1048576)} MB)...`);
  // Items a batch couldn't create get one more try on their own after the batches.
  const retryAlone = [];
  // Sizes to use next, in order, when a refused batch is being split to find the item causing it.
  const forcedSizes = [];
  let i = 0;
  let refusedBatches = 0;
  let batchCap = BATCH_SIZE;
  while (i < batchableItems.length) {
    if (isCancelled()) return cancelledResult();

    let wanted = forcedSizes.length > 0
      ? forcedSizes.shift()
      : itemsWithinBudget(batchableItems, i, Math.min(batchCap, batchableItems.length - i));
    // Shrink the batch so it fits under the rate limit.
    const size = destSDK.limits
      ? await acquire(destSDK.limits, 'write', { units: wanted, flexible: true })
      : wanted;
    if (size < wanted && forcedSizes.length > 0) forcedSizes.unshift(wanted - size);
    const chunk = batchableItems.slice(i, i + size);
    const what = chunk.length === 1 ? `Creating "${chunk[0].sourceTitle}"` : `Creating ${chunk.length} items in one batch`;
    if (onProgress) onProgress(processedItems, items.length, successCount, failureCount, `${what}...`);
    i += size;
    const rateLimitedEntries = [];
    let rateLimitError = null;
    const before = processedItems;
    const estimate = onProgress ? estimator.start(chunk, (done, seconds) => onProgress(
      processedItems, items.length, successCount, failureCount,
      seconds >= 2 ? `${what} (${seconds}s)...` : `${what}...`, before + done)) : null;

    try {
      const createBatch = () => destSDK.client.items.createAll(newVaultId, chunk.map(entry => entry.newItem));
      let batchResponse;
      try {
        batchResponse = destSDK.limits
          ? await destSDK.withFreshSignIn(() => retryWithBackoff(createBatch, { retryRateLimits: false }))
          : await destSDK.retry(createBatch);
      } finally {
        estimate?.stop(!!batchResponse);
      }

      refusedBatches = 0;
      for (let j = 0; j < batchResponse.individualResponses.length; j++) {
        const res = batchResponse.individualResponses[j];
        const entry = chunk[j];

        if (res.content) {
          recordSuccess(entry, res.content, 'Batch created');
          entry.newItem = null;
        } else if (res.error) {
          const errMsg = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
          // Rate limited, not a real failure. This item gets retried after the pause.
          if (destSDK.limits && isRateLimitError({ message: errMsg })) {
            rateLimitedEntries.push(entry);
            rateLimitError = new Error(errMsg);
            continue;
          }
          if (DEBUG_ENABLED) {
            logger.error(vaultId, `[DEBUG] Batch create FAILED for "${entry.sourceTitle}" [${entry.sourceId}]: ${errMsg}`);
            logger.error(vaultId, `[DEBUG] Full payload that failed: ${JSON.stringify(sanitizeItemForLog(entry.newItem))}`);
          }
          logger.warning(vaultId, `"${entry.sourceTitle}" [${entry.sourceId}] wasn't created in its batch (${errMsg}). Trying it on its own`);
          retryAlone.push({ entry, batchError: errMsg });
        }
      }
    } catch (error) {
      if (error instanceof MigrationCancelledError) throw error;
      // 1Password refused the whole batch. Put it back, wait, and try a smaller one.
      if (destSDK.limits && isRateLimitError(error) && refusedBatches < 10) {
        refusedBatches++;
        i -= chunk.length;
        if (chunk.length > 1) {
          destSDK.limits.monitor.assumePerItem('write');
          batchCap = Math.max(1, Math.floor(chunk.length / 2));
        }
        logger.warning(vaultId, `A batch of ${chunk.length} item(s) was rate limited. Pausing, then retrying it`);
        await waitOutRateLimit(destSDK.limits, 'write', error);
        continue;
      }
      if (DEBUG_ENABLED) {
        logger.error(vaultId, `[DEBUG] Entire batch failed containing ${chunk.length} item(s): ${formatErrorForLog(error)}`);
      }
      // Split the batch in half and send each half, until the item causing it is on its own.
      if (chunk.length > 1) {
        const half = Math.floor(chunk.length / 2);
        logger.warning(vaultId, `A batch of ${chunk.length} item(s) was refused (${error.message}). Splitting it to find the item causing it`);
        i -= chunk.length;
        forcedSizes.unshift(half, chunk.length - half);
        continue;
      }
      logger.warning(vaultId, `"${chunk[0].sourceTitle}" [${chunk[0].sourceId}] was refused in a batch (${error.message}). Trying it on its own`);
      retryAlone.push({ entry: chunk[0], batchError: error.message });
    }

    if (rateLimitedEntries.length > 0) {
      logger.warning(vaultId, `${rateLimitedEntries.length} item(s) in a batch were rate limited. Pausing, then retrying them`);
      batchableItems.splice(i, 0, ...rateLimitedEntries);
      await waitOutRateLimit(destSDK.limits, 'write', rateLimitError);
    }

    if (onProgress) onProgress(processedItems, items.length, successCount, failureCount);
  }

  for (const { entry, batchError } of [...individualItems.map(entry => ({ entry })), ...retryAlone]) {
    if (isCancelled()) return cancelledResult();
    if (onProgress) onProgress(processedItems, items.length, successCount, failureCount, `Creating "${entry.sourceTitle}" on its own...`);
    if (DEBUG_ENABLED) {
      logger.info(vaultId, `[DEBUG] Individual create payload: ${JSON.stringify(sanitizeItemForLog(entry.newItem))}`);
    }

    try {
      const createdItem = await destSDK.retry(() => destSDK.client.items.create(entry.newItem), { kind: 'write' });
      recordSuccess(entry, createdItem, batchError ? 'Created on its own, after its batch failed,' : 'Created');
    } catch (error) {
      if (error instanceof MigrationCancelledError) throw error;
      if (DEBUG_ENABLED) {
        logger.error(vaultId, `[DEBUG] Individual create FAILED for "${entry.sourceTitle}" [${entry.sourceId}]: ${formatErrorForLog(error)}`);
      }
      recordFailure(entry.sourceId, entry.sourceTitle, error);
    }
    entry.newItem = null;

    if (onProgress) onProgress(processedItems, items.length, successCount, failureCount);
  }

  if (itemsWithRefs.length > 0) {
    logger.info(vaultId, `Phase 3: Adding reference fields to ${itemsWithRefs.length} items...`);

    const addReferences = (destItem, ref) => {
      let updated = false;
      for (const refField of ref.refFields) {
        const newRefId = idMap.get(refField.sourceRefId);
        if (!newRefId) {
          logger.warning(vaultId, `Reference target ${refField.sourceRefId} not found in ID map. The referenced item may not have been migrated`);
          continue;
        }
        if (!destItem.fields) destItem.fields = [];
        destItem.fields.push({
          id: refField.fieldId,
          title: refField.title || "Reference",
          fieldType: sdk.ItemFieldType.Reference,
          value: newRefId,
          ...(refField.sectionId ? { sectionId: refField.sectionId } : {})
        });
        if (refField.sectionId && destItem.sections && !destItem.sections.some(s => s.id === refField.sectionId)) {
          destItem.sections.push({ id: refField.sectionId, title: refField.sectionId });
        }
        updated = true;
        logger.info(vaultId, `Added reference field "${refField.fieldId}" to item ${ref.destItemId}: ${refField.sourceRefId} → ${newRefId}`);
      }
      return updated;
    };

    for (const ref of itemsWithRefs) {
      try {
        // References need the new item IDs, so they're added once everything exists.
        if (!addReferences(ref.createdItem, ref)) continue;
        try {
          await destSDK.retry(() => destSDK.client.items.put(ref.createdItem), { kind: 'write' });
        } catch (putError) {
          if (putError instanceof MigrationCancelledError || isRateLimitError(putError)) throw putError;
          logger.info(vaultId, `Update of ${ref.destItemId} from its created copy failed (${errorMessage(putError)}), retrying with a fresh copy`);
          // Our copy may be out of date, so get a fresh one and try again.
          const fresh = await destSDK.retry(() => destSDK.client.items.get(newVaultId, ref.destItemId));
          addReferences(fresh, ref);
          await destSDK.retry(() => destSDK.client.items.put(fresh), { kind: 'write' });
        }
        logger.info(vaultId, `Updated item ${ref.destItemId} with reference fields`);
      } catch (error) {
        if (error instanceof MigrationCancelledError) throw error;
        logger.warning(vaultId, `Failed to add references for item ${ref.destItemId}: ${error.message}`);
      } finally {
        ref.createdItem = null;
      }
    }
  } else {
    logger.info(vaultId, `Phase 3: No reference fields to remap`);
  }

  return { cancelled: false, successCount, failureCount, failures };
}

async function migrateVault({ vaultId, vaultName, suffix = '', isPersonal = false, sourceData, destSDK, destOpAuth, isCancelled, onProgress = null, destVaultId = null }) {
  const { items, sourceItemCount } = sourceData;
  logger.info(vaultId, `Starting migration for vault ${vaultName} (${items.length} items, source count ${sourceItemCount})`);

  const newVaultId = destVaultId || (isPersonal
    ? await findDestPrivateVault(vaultId, destSDK)
    : await createDestVault(vaultId, vaultName, suffix, destSDK, destOpAuth));

  if (items.length === 0) {
    logger.logVaultComplete(vaultId, vaultName, { sourceItemCount, destItemCount: 0, successCount: 0, failureCount: 0 });
    return { itemsLength: 0, failures: [], sourceItemCount, destItemCount: 0, successCount: 0, failureCount: 0 };
  }

  if (isCancelled()) {
    logger.info(vaultId, `Migration cancelled by user`);
    return { itemsLength: items.length, failures: [], sourceItemCount, destItemCount: null, successCount: 0, failureCount: 0 };
  }

  const write = await writeItemsToVault({ vaultId, vaultName, items, newVaultId, destSDK, isCancelled, onProgress });
  const { successCount, failureCount, failures } = write;

  if (write.cancelled) {
    logger.info(vaultId, `Migration cancelled by user`);
    return { itemsLength: items.length, failures, sourceItemCount, destItemCount: null, successCount, failureCount };
  }

  const destItemCount = await destVaultItemCount(newVaultId, destSDK, sourceItemCount);
  logger.info(vaultId, `Destination item count: ${destItemCount}`);
  logger.info(vaultId, `Migration completed - Success: ${successCount}, Failed: ${failureCount}`);

  logger.logVaultComplete(vaultId, vaultName, { sourceItemCount, destItemCount, successCount, failureCount });

  if (sourceItemCount === destItemCount && failureCount === 0) {
    logger.info(vaultId, `Successfully migrated all ${sourceItemCount} items`);
  } else if (!isPersonal) {
    logger.warning(vaultId, `Item count mismatch - Source: ${sourceItemCount}, Destination: ${destItemCount}, Failed: ${failureCount}`);
  }

  return { itemsLength: items.length, failures, sourceItemCount, destItemCount, successCount, failureCount };
}

// Uses the count from the vault overview, and only lists every item if it doesn't match.
async function destVaultItemCount(vaultId, destSDK, expected) {
  try {
    const overview = await destSDK.retry(() => destSDK.client.vaults.getOverview(vaultId));
    if (typeof overview.activeItemCount === 'number' && overview.activeItemCount === expected) {
      return overview.activeItemCount;
    }
  } catch (error) {
    if (error instanceof MigrationCancelledError) throw error;
    logger.warning(vaultId, `Could not read the destination vault overview: ${error.message}`);
  }
  return getVaultItemCount(vaultId, destSDK, { skipArchived: true });
}

app.post('/migration/migrate-vault', async (req, res) => {
  const { vaultId, vaultName, sourceToken, destToken, authMode, sourceAccountName, destAccountName } = req.body;

  if (!vaultId || !vaultName) {
    return res.status(400).json({ success: false, message: 'Vault ID and vault name are required' });
  }

  try {
    const sourceSDK = createSDKInstance(authMode, sourceToken, sourceAccountName);
    await sourceSDK.initializeClient();
    const destSDK = createSDKInstance(authMode, destToken, destAccountName);
    await destSDK.initializeClient();

    const opSource = authMode === 'desktop' ? { account: sourceAccountName } : { token: sourceToken };
    const opDest = authMode === 'desktop' ? { account: destAccountName } : { token: destToken };

    let sourceData;
    try {
      sourceData = await readSourceVault(vaultId, sourceSDK, opSource);
    } catch (error) {
      throw new Error(`Item listing failed: ${error.message}`);
    }

    const result = await migrateVault({ vaultId, vaultName, sourceData, destSDK, destOpAuth: opDest, isCancelled: () => isMigrationCancelled });
    const { itemsLength, failures, sourceItemCount, destItemCount, successCount, failureCount } = result;
    const success = failureCount === 0 && sourceItemCount === destItemCount;

    res.json({
      success,
      message: success
        ? `Successfully migrated vault "${vaultName}" with ${itemsLength} items`
        : `Vault "${vaultName}" migration completed with ${failureCount} failures out of ${itemsLength} items`,
      failures,
      stats: { successCount, failureCount, sourceItemCount, destItemCount }
    });
  } catch (error) {
    logger.error(vaultId, `Migration endpoint failed: ${error.message}`);
    res.status(500).json({ success: false, message: `Failed to migrate vault: ${error.message}` });
  }
});
function createSDKInstance(authMode, token, accountName) {
  if (authMode === 'desktop') {
    return new OnePasswordSDK({ authMode: 'desktop', accountName });
  }
  return new OnePasswordSDK({ token });
}

app.post('/migration/start', (req, res) => {
  const { sourceToken, destToken, authMode, sourceAccountName, destAccountName, useEnv, vaults } = req.body;

  const validatedMode = VALID_AUTH_MODES_SERVER.includes(authMode) ? authMode : 'service-account';
  const validatedVaults = Array.isArray(vaults) ? vaults.filter(v =>
    v && typeof v.vaultId === 'string' && typeof v.vaultName === 'string'
  ).map(v => ({ ...v, itemCount: Number.isFinite(v.itemCount) ? v.itemCount : 0 })) : null;

  const sessionId = crypto.randomUUID();
  migrationSessions.set(sessionId, {
    sourceToken: typeof sourceToken === 'string' ? sourceToken : null,
    destToken: typeof destToken === 'string' ? destToken : null,
    authMode: validatedMode,
    sourceAccountName: typeof sourceAccountName === 'string' ? sourceAccountName : '',
    destAccountName: typeof destAccountName === 'string' ? destAccountName : '',
    useEnv: useEnv === true || useEnv === 'true',
    vaults: validatedVaults,
    createdAt: Date.now(),
    timer: setTimeout(() => migrationSessions.delete(sessionId), SESSION_TTL),
  });

  res.json({ success: true, sessionId });
});

app.get('/migration/migrate-all-vaults', async (req, res) => {
  const { sessionId } = req.query;
  const session = sessionId ? migrationSessions.get(sessionId) : null;

  if (!session) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.flushHeaders();
    res.write(`data: ${JSON.stringify({ success: false, message: 'Invalid or expired migration session', finished: true })}\n\n`);
    res.end();
    return;
  }

  // Sessions are single use, so forget the tokens right away.
  clearTimeout(session.timer);
  migrationSessions.delete(sessionId);

  const { sourceToken, destToken, authMode, sourceAccountName, destAccountName, useEnv, vaults: selectedVaults } = session;
  let mode, resolvedSourceToken, resolvedDestToken, resolvedSourceAccount, resolvedDestAccount;

  if (useEnv && envConfig.loaded) {
    mode = envConfig.authMode || 'service-account';
    resolvedSourceToken = envConfig.sourceToken;
    resolvedDestToken = envConfig.destToken;
    resolvedSourceAccount = envConfig.sourceAccount;
    resolvedDestAccount = envConfig.destAccount;
  } else {
    mode = VALID_AUTH_MODES_SERVER.includes(authMode) ? authMode : 'service-account';
    resolvedSourceToken = sourceToken;
    resolvedDestToken = destToken;
    resolvedSourceAccount = sourceAccountName;
    resolvedDestAccount = destAccountName;
  }

  const missingCredentials = mode === 'desktop'
    ? (!resolvedSourceAccount || !resolvedDestAccount ? 'Source and destination account names are required' : null)
    : (!resolvedSourceToken || !resolvedDestToken ? 'Source token and destination token are required' : null);

  if (missingCredentials) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.flushHeaders();
    res.write(`data: ${JSON.stringify({ success: false, message: missingCredentials, finished: true })}\n\n`);
    res.end();
    return;
  }

  isMigrationCancelled = false;
  logger.info(null, `Starting bulk vault migration (mode: ${mode})`);

  // Every page watching this migration (this one, and any that reattach after a refresh) gets the events.
  const feed = new MigrationFeed(sessionId, {
    authMode: mode,
    sourceAccountName: mode === 'desktop' ? resolvedSourceAccount : '',
    destAccountName: mode === 'desktop' ? resolvedDestAccount : '',
    vaults: (selectedVaults || []).map(v => ({ id: v.vaultId, name: v.vaultName, vaultType: v.vaultType || 'shared', itemCount: v.itemCount || 0 })),
  });
  migrationFeeds.set(sessionId, feed);
  const sseWrite = (payload) => feed.publish(payload);

  const control = new MigrationControl({ id: sessionId, emit: sseWrite, log: logger });
  activeMigrations.set(sessionId, control);
  const isCancelled = () => isMigrationCancelled || control.cancelled;

  feed.attach(res, { onEmpty: () => {
    control.clientDisconnected();
    logger.info(null, 'No page is watching the migration. It will continue on the server');
  } });
  function finish(payload) {
    activeMigrations.delete(sessionId);
    sseWrite(payload);
    feed.end();
  }

  const vaultResults = [];
  const vaultOutcome = (vault, result, isPersonal = false) => {
    const { itemsLength, sourceItemCount, destItemCount, successCount, failureCount } = result;
    const success = isPersonal
      ? (failureCount === 0 && successCount === itemsLength)
      : (failureCount === 0 && sourceItemCount === destItemCount);
    return {
      vaultId: vault.id, vaultName: vault.name, success,
      message: success
        ? `Successfully migrated vault "${vault.name}" with ${itemsLength} items`
        : `Vault "${vault.name}" completed with ${failureCount} failures out of ${itemsLength} items`,
      sourceItemCount, destItemCount, successCount, failureCount, phase: 'completed'
    };
  };
  const failedOutcome = (vault, message, error, extra = {}) => ({
    vaultId: vault.id, vaultName: vault.name, success: false, message, error, phase: 'failed', ...extra
  });
  // The progress bar only counts items written. While records are being read, the status text shows
  // how far along the read is, but the bar stays put. Read updates are throttled to a few a second.
  let lastProgress = 0;
  const sendProgress = (progress, outcome) => {
    lastProgress = Math.max(lastProgress, progress);
    sseWrite({ progress: lastProgress, outcome });
  };
  const throttled = (fn, ms = 250) => {
    let last = 0;
    return (done, total, ...rest) => {
      const now = Date.now();
      if (now - last < ms && done !== total) return;
      last = now;
      fn(done, total, ...rest);
    };
  };
  const throttledRead = (fn, ms = 250) => {
    let last = 0;
    return (index, done, total) => {
      const now = Date.now();
      if (now - last < ms && done !== total && done !== 0) return;
      last = now;
      fn(index, done, total);
    };
  };
  const progressCallbackFor = (vault, index, totalVaults, verb, overall) =>
    (itemsProcessed, totalItems, successCount, failureCount, activity, estimatedDone = itemsProcessed) => {
      sendProgress(overall(index, totalItems ? Math.max(itemsProcessed, estimatedDone) / totalItems : 1), {
        vaultId: vault.id, vaultName: vault.name, phase: 'migrating',
        message: activity || `${verb} items (${itemsProcessed}/${totalItems})...`,
        activity, itemsProcessed, totalItems, successCount, failureCount
      });
    };
  const finalMessage = (totalVaults, extra = {}) => {
    const failedVaults = vaultResults.filter(r => !r.success);
    return {
      success: failedVaults.length === 0,
      message: failedVaults.length === 0
        ? `Successfully migrated all ${totalVaults} vaults`
        : `Migration completed with ${failedVaults.length} vault failures out of ${totalVaults} vaults`,
      results: vaultResults, summary: logger.getSummary(), finished: true, ...extra
    };
  };
  const cancelledMessage = () => ({ success: false, message: 'Migration cancelled by user', results: vaultResults, finished: true });

  try {
    if (mode === 'desktop') {
      sseWrite({ progress: 0, outcome: { phase: 'desktop-source-connect', message: `Connecting to source account "${resolvedSourceAccount}"...` } });

      const sourceSDK = createSDKInstance('desktop', null, resolvedSourceAccount);
      await sourceSDK.initializeClient();

      const vaultsToMigrate = selectedVaults && selectedVaults.length > 0
        ? selectedVaults.map(v => ({ id: v.vaultId, name: v.vaultName, vaultType: v.vaultType || 'shared', suffix: v.suffix || '' }))
        : (await sourceSDK.listVaults()).map(v => ({ id: v.id, name: v.name, vaultType: v.vaultType || 'shared', suffix: '' }));
      const totalVaults = vaultsToMigrate.length;
      const writeProgress = (index, fraction) => ((index + fraction) / totalVaults) * 100;

      sseWrite({ progress: 0, outcome: { phase: 'desktop-reading', message: `Reading ${totalVaults} vault(s) from source account...` } });
      const allVaultData = await desktopReadAllVaults(sourceSDK, vaultsToMigrate, resolvedSourceAccount, isCancelled,
        throttledRead((vaultIdx, done, total) => {
          const vault = vaultsToMigrate[vaultIdx];
          const counts = total ? ` (${done}/${total} items)` : '';
          sendProgress(lastProgress,
            { phase: 'desktop-reading', message: `Reading vault ${vaultIdx + 1}/${totalVaults}, "${vault.name}"${counts}...` });
        }));

      const totalItemsRead = allVaultData.reduce((sum, v) => sum + v.items.length, 0);
      logger.info(null, `[Desktop] Phase 1 complete: read ${totalItemsRead} items from ${totalVaults} vaults`);

      if (isCancelled()) return finish(cancelledMessage());

      sendProgress(lastProgress, { phase: 'desktop-dest-connect', message: `Connecting to destination account "${resolvedDestAccount}"...` });
      const destSDK = createSDKInstance('desktop', null, resolvedDestAccount);
      await destSDK.initializeClient();
      sendProgress(lastProgress, { phase: 'desktop-dest-connect', message: `Connected to "${resolvedDestAccount}", starting migration...` });

      for (const [index, vaultData] of allVaultData.entries()) {
        if (isCancelled()) return finish(cancelledMessage());

        const vault = { id: vaultData.vaultId, name: vaultData.vaultName };

        if (vaultData.error) {
          const outcome = failedOutcome(vault, `Skipped because the source read failed: ${vaultData.error}`, vaultData.error, {
            sourceItemCount: vaultData.sourceItemCount || 0, failureCount: vaultData.sourceItemCount || 0, successCount: 0
          });
          vaultResults.push(outcome);
          sendProgress(writeProgress(index, 1), outcome);
          continue;
        }

        sendProgress(writeProgress(index, 0), { vaultId: vault.id, vaultName: vault.name, phase: 'preparing', message: `Creating vault and writing items...` });

        const isPersonal = vaultData.vaultType === 'personal';
        try {
          const result = await migrateVault({
            vaultId: vault.id, vaultName: vault.name, suffix: vaultData.suffix, isPersonal,
            sourceData: vaultData, destSDK, destOpAuth: { account: resolvedDestAccount },
            isCancelled: isCancelled,
            onProgress: progressCallbackFor(vault, index, totalVaults, 'Writing', writeProgress),
          });
          const outcome = vaultOutcome(vault, result, isPersonal);
          vaultResults.push(outcome);
          sendProgress(writeProgress(index, 1), outcome);
        } catch (error) {
          logger.error(vault.id, `[Desktop Phase 2] Vault write failed: ${error.message}`);
          logger.logFailedVault(vault.id, vault.name, error);
          const outcome = failedOutcome(vault, `Failed: ${error.message}`, error.message);
          vaultResults.push(outcome);
          sendProgress(writeProgress(index, 1), outcome);
        } finally {
          // This vault is written, so free its items.
          vaultData.items = [];
        }
      }

      return finish(finalMessage(totalVaults));
    }

    const sourceSDK = createSDKInstance(mode, resolvedSourceToken, resolvedSourceAccount);
    await sourceSDK.initializeClient();
    const destSDK = createSDKInstance('service-account', resolvedDestToken);
    await destSDK.initializeClient();

    const destMonitor = rateLimitMonitorFor(resolvedDestToken, 'destination');
    sourceSDK.attachRateLimits({ monitor: rateLimitMonitorFor(resolvedSourceToken, 'source'), control });
    destSDK.attachRateLimits({ monitor: destMonitor, control });
    if (await destMonitor.exclusive(() => destMonitor.refresh())) control.reportUsage(destMonitor);

    const vaultsToMigrate = selectedVaults && selectedVaults.length > 0
      ? selectedVaults.map(v => ({ id: v.vaultId, name: v.vaultName, suffix: v.suffix || '' }))
      : await sourceSDK.listVaults();
    const totalVaults = vaultsToMigrate.length;
    const opSource = { token: resolvedSourceToken };
    const opDest = { token: resolvedDestToken };
    const writeProgress = (index, fraction) => ((index + fraction) / totalVaults) * 100;
    let currentIndex = 0;

    // Read the next vault while the current one is being written. While that happens, its reads show
    // as "reading ahead" on its row without moving the progress bar. Each destination vault is created
    // while its source is being read, since creating it doesn't need the items.
    const createdAhead = new Map();
    const startRead = (vault, index) => {
      createdAhead.set(vault.id, createDestVault(vault.id, vault.name, vault.suffix || '', destSDK, opDest)
        .then(id => ({ id }), error => ({ error })));
      return readSourceVault(vault.id, sourceSDK, opSource, throttled((done, total) => {
        const ahead = index !== currentIndex;
        sendProgress(lastProgress,
          { vaultId: vault.id, vaultName: vault.name, phase: 'reading', itemsRead: done, totalItems: total, ahead });
      })).then(data => ({ data }), error => ({ error }));
    };
    // A vault created ahead that nothing will be written to (its read failed, or the migration was
    // cancelled) is empty, so remove it rather than leave an empty "(Migrated)" vault behind.
    const discardCreatedAhead = async (vault, why) => {
      const created = createdAhead.get(vault.id);
      createdAhead.delete(vault.id);
      const result = created && await created;
      if (!result?.id) return;
      try {
        await destSDK.client.vaults.delete(result.id);
        logger.info(vault.id, `Removed the empty destination vault [${result.id}] created for "${vault.name}" (${why})`);
      } catch (error) {
        logger.warning(vault.id, `The destination vault [${result.id}] created for "${vault.name}" is empty and could not be removed (${error.message}). Delete it by hand if you don't want it`);
      }
    };
    const discardAllCreatedAhead = (why) => Promise.all(
      vaultsToMigrate.filter(v => createdAhead.has(v.id)).map(v => discardCreatedAhead(v, why)));
    const cancelled = async () => {
      logger.info(null, 'Bulk migration cancelled by user');
      await discardAllCreatedAhead('migration cancelled');
      return finish(cancelledMessage());
    };
    let nextRead = totalVaults > 0 ? startRead(vaultsToMigrate[0], 0) : null;

    for (const [index, vault] of vaultsToMigrate.entries()) {
      currentIndex = index;
      if (isCancelled()) return cancelled();

      sendProgress(writeProgress(index, 0), { vaultId: vault.id, vaultName: vault.name, phase: 'preparing', message: 'Preparing vault...' });

      let read = await nextRead;
      nextRead = index + 1 < totalVaults && !isCancelled() ? startRead(vaultsToMigrate[index + 1], index + 1) : null;

      try {
        if (read.error instanceof MigrationCancelledError) throw read.error;
        if (read.error) {
          logger.error(vault.id, `Failed to list items: ${read.error.message}`);
          await discardCreatedAhead(vault, 'its items could not be read');
          throw new Error(`Item listing failed: ${read.error.message}`);
        }
        if (isCancelled()) return cancelled();

        const created = await createdAhead.get(vault.id);
        createdAhead.delete(vault.id);
        if (created.error) throw created.error;

        const result = await migrateVault({
          vaultId: vault.id, vaultName: vault.name, suffix: vault.suffix || '',
          sourceData: read.data, destSDK, destOpAuth: opDest, destVaultId: created.id,
          isCancelled: isCancelled,
          onProgress: progressCallbackFor(vault, index, totalVaults, 'Migrating', writeProgress),
        });
        const outcome = vaultOutcome(vault, result);
        vaultResults.push(outcome);
        sendProgress(((index + 1) / totalVaults) * 100, outcome);
      } catch (error) {
        if (error instanceof MigrationCancelledError) return cancelled();
        logger.error(vault.id, `Vault migration failed: ${error.message}`);
        logger.logFailedVault(vault.id, vault.name, error);
        const outcome = failedOutcome(vault, `Failed to migrate vault "${vault.name}": ${error.message}`, error.message);
        vaultResults.push(outcome);
        sendProgress(((index + 1) / totalVaults) * 100, outcome);
      } finally {
        read = null;
      }
    }

    await destMonitor.exclusive(() => destMonitor.refresh());
    finish(finalMessage(totalVaults, { rateLimit: destMonitor.snapshot() }));
  } catch (error) {
    if (error instanceof MigrationCancelledError) return finish(cancelledMessage());
    logger.error(null, `Bulk migration failed: ${error.message}`);
    finish({ success: false, message: `Failed to migrate vaults: ${error.message}`, finished: true });
  }
});
app.get('/migration/download-log', async (req, res) => {
  const summary = logger.getSummary();
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');

  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename=migration-log-${timestamp}.txt`);
  res.write(`1Password Vault Migration Log
Generated: ${new Date().toISOString()}
Total Entries: ${summary.totalEntries}
Errors: ${summary.errors}
Warnings: ${summary.warnings}
Vaults Processed: ${summary.vaults}
Failed Vaults: ${summary.failedVaults}
Failed Items: ${summary.failedItems}

${'='.repeat(80)}

${logger.getVaultStatsSummary()}
${logger.getFailureSummary()}

${'='.repeat(80)}
DETAILED LOG
${'='.repeat(80)}

`);

  try {
    await logger.pipeGlobalLog(res);
  } catch (error) {
    res.write(`\n[could not read log file: ${error.message}]\n`);
  }
  res.end();
});

app.get('/migration/download-vault-log/:vaultId', async (req, res) => {
  const vaultId = String(req.params.vaultId).replace(/[^a-zA-Z0-9]/g, '');
  const logContent = vaultId ? await logger.getVaultLog(vaultId) : '';

  if (!logContent) {
    return res.status(404).send('No log found for this vault');
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename=vault-${vaultId}-log-${timestamp}.txt`);
  res.send(`1Password Vault Migration Log
Vault ID: ${vaultId}
Generated: ${new Date().toISOString()}

${'='.repeat(80)}

${logContent}`);
});

app.get('/migration/stats', (req, res) => {
  res.json(logger.getSummary());
});

app.post('/migration/clear-logs', (req, res) => {
  logger.clear();
  res.json({ success: true, message: 'Logs cleared successfully' });
});
app.get('/migration/debug', (req, res) => {
  res.json({ enabled: DEBUG_ENABLED });
});

app.post('/migration/debug', (req, res) => {
  const { enabled } = req.body;
  DEBUG_ENABLED = enabled === true || enabled === 'true' || enabled === 1;
  logger.info(null, `Debug logging ${DEBUG_ENABLED ? 'ENABLED' : 'DISABLED'}`);
  res.json({ success: true, enabled: DEBUG_ENABLED });
});
const MAX_CACHED_CLIENTS = 8;
// Signed-in SDK clients get reused so each token only signs in once.
const clientCache = new Map();

function clientCacheKey(authMode, token, accountName) {
  const secret = authMode === 'desktop' ? `desktop:${accountName}` : `token:${token}`;
  return crypto.createHash('sha256').update(secret).digest('hex');
}

function isAuthExpiredError(error) {
  return (sdk.AuthExpiredError && error instanceof sdk.AuthExpiredError)
    || /auth(entication)? (has )?expired|session (has )?expired/i.test(errorMessage(error));
}

class OnePasswordSDK {
  constructor({ token, authMode = 'service-account', accountName } = {}) {
    this.token = token || null;
    this.authMode = authMode;
    this.accountName = accountName || null;
    this.client = null;
    this.cacheKey = clientCacheKey(this.authMode, this.token, this.accountName);
  }

  async initializeClient() {
    if (this.client) return;

    const cached = clientCache.get(this.cacheKey);
    if (cached) {
      try {
        this.client = await cached;
        return;
      } catch {
      }
    }

    const signIn = this.#createClient();
    clientCache.set(this.cacheKey, signIn);
    if (clientCache.size > MAX_CACHED_CLIENTS) {
      clientCache.delete(clientCache.keys().next().value);
    }
    try {
      this.client = await signIn;
    } catch (error) {
      clientCache.delete(this.cacheKey);
      logger.error(null, `Failed to initialize client: ${error.message}`);
      throw new Error(`Failed to initialize client: ${error.message}`);
    }
  }

  async #createClient() {
    logger.info(null, `Initializing 1Password SDK client (mode: ${this.authMode})`);
    if (this.authMode === 'desktop') {
      if (!this.accountName) throw new Error('Account name is required for desktop auth.');
      return sdk.createClient({
        auth: new sdk.DesktopAuth(this.accountName),
        integrationName: "1Password Vault Migration Tool",
        integrationVersion: "2.1.0",
      });
    }
    if (!this.token) throw new Error('Service account token is required.');
    return sdk.createClient({
      auth: this.token,
      integrationName: "1Password Vault Migration Tool",
      integrationVersion: "2.1.0",
    });
  }


  attachRateLimits(limits) {
    this.limits = limits;
  }

  async retry(fn, { kind = 'read', units = 1 } = {}) {
    return this.withFreshSignIn(() => this.#retryOnce(fn, { kind, units }));
  }

  async withFreshSignIn(fn) {
    const clientUsed = this.client;
    try {
      return await fn();
    } catch (error) {
      if (!clientUsed || !isAuthExpiredError(error)) throw error;
      await this.#replaceExpiredClient(clientUsed, error);
      return fn();
    }
  }

  // Several requests can hit an expired sign-in at once, so only one of them signs in again.
  async #replaceExpiredClient(expired, error) {
    if (this.client !== expired) return;
    if (!this.reSigningIn) {
      this.reSigningIn = (async () => {
        const cached = clientCache.get(this.cacheKey);
        const cachedClient = cached ? await cached.catch(() => null) : null;
        if (cachedClient && cachedClient !== expired) {
          this.client = cachedClient;
          return;
        }
        logger.warning(null, `SDK sign-in expired (${errorMessage(error)}), signing in again`);
        const signIn = this.#createClient();
        clientCache.set(this.cacheKey, signIn);
        try {
          this.client = await signIn;
        } catch (signInError) {
          clientCache.delete(this.cacheKey);
          throw signInError;
        }
      })().finally(() => { this.reSigningIn = null; });
    }
    await this.reSigningIn;
  }

  async #retryOnce(fn, { kind, units }) {
    if (!this.limits) {
      return retryWithBackoff(fn, { waitForAppUnlock: this.authMode === 'desktop' });
    }
    for (let attempt = 0; ; attempt++) {
      await acquire(this.limits, kind, { units });
      try {
        return await retryWithBackoff(fn, { retryRateLimits: false });
      } catch (error) {
        if (attempt < 5 && isRateLimitError(error)) {
          await waitOutRateLimit(this.limits, kind, error);
          continue;
        }
        throw error;
      }
    }
  }

  async listVaults() {
    try {
      if (!this.client) await this.initializeClient();
      const vaults = await this.retry(() => this.client.vaults.list());
      const vaultList = vaults.map(vault => {
        const name = vault.title;
        const vName = (name || '').toLowerCase();
        const isPersonal = String(vault.vaultType || '').toLowerCase() === 'personal'
          || vName === 'private' || vName === 'employee';
        return { id: vault.id, name, vaultType: isPersonal ? 'personal' : 'shared', activeItemCount: vault.activeItemCount };
      });

      logger.info(null, `Listed ${vaultList.length} vaults (${vaultList.filter(v => v.vaultType === 'personal').length} personal, ${vaultList.filter(v => v.vaultType === 'shared').length} shared)`);
      return vaultList;
    } catch (error) {
      logger.error(null, `Failed to list vaults: ${error.message}`);
      throw new Error(`Failed to list vaults: ${error.message}`);
    }
  }

  async listVaultItems(vaultId, onProgress = null) {
    try {
      if (!this.client) await this.initializeClient();
      logger.info(vaultId, `Listing items for vault`);

      const itemOverviews = await this.retry(() => this.client.items.list(vaultId));
      const itemIds = itemOverviews.map(item => item.id);
      logger.info(vaultId, `Found ${itemIds.length} item IDs, batch fetching full details...`);

      if (itemIds.length === 0) return { items: [], sourceItemCount: 0 };
      if (DEBUG_ENABLED) {
        for (const overview of itemOverviews) {
          logger.info(vaultId, `[DEBUG] Found item in overview list: "${overview.title}" [${overview.id}] category="${overview.category}"`);
        }
      }

      const chunks = [];
      for (let i = 0; i < itemIds.length; i += BATCH_GET_SIZE) {
        chunks.push(itemIds.slice(i, i + BATCH_GET_SIZE));
      }

      const chunkResults = await mapWithConcurrency(chunks, READ_CONCURRENCY, (chunkIds) => this.#getItems(vaultId, chunkIds));
      const fullItems = chunkResults.flat();

      logger.info(vaultId, `Fetched ${fullItems.length} full items, processing fields and files...`);

      let read = 0;
      const processed = await mapWithConcurrency(fullItems, READ_CONCURRENCY, async (fullItem) => {
        const itemData = await this.#toItemData(vaultId, fullItem);
        read++;
        if (onProgress) onProgress(read, fullItems.length);
        return itemData;
      });
      const items = processed.filter(Boolean);

      logger.info(vaultId, `Listed ${items.length} items successfully`);
      return { items, sourceItemCount: itemOverviews.length };

    } catch (error) {
      logger.error(vaultId, `Failed to list items: ${error.message}`);
      throw new Error(`Failed to list items for vault ${vaultId}: ${error.message}`);
    }
  }

  async #getItems(vaultId, chunkIds) {
    const fullItems = [];
    try {
      const batchResponse = await this.retry(() => this.client.items.getAll(vaultId, chunkIds), { units: chunkIds.length });

      for (let idx = 0; idx < batchResponse.individualResponses.length; idx++) {
        const res = batchResponse.individualResponses[idx];
        if (res.content) {
          if (DEBUG_ENABLED) {
            logger.info(vaultId, `[DEBUG] getAll returned "${res.content.title}" [${res.content.id}], category: "${res.content.category}", fields: ${res.content.fields?.length || 0}, sections: ${res.content.sections?.length || 0}`);
            logger.info(vaultId, `[DEBUG] getAll raw fields: ${JSON.stringify(redactFieldsForLog(res.content.fields || []))}`);
          }
          fullItems.push(res.content);
        } else if (res.error) {
          const errMsg = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
          logger.error(vaultId, `Batch get failed for item [${chunkIds[idx] || 'unknown'}]: ${errMsg}`);
        }
      }
    } catch (batchError) {
      logger.warning(vaultId, `Batch getAll failed, falling back to individual gets: ${batchError.message}`);
      for (const id of chunkIds) {
        try {
          fullItems.push(await this.retry(() => this.client.items.get(vaultId, id)));
        } catch (itemError) {
          logger.error(vaultId, `Failed to get item ${id}: ${formatErrorForLog(itemError)}`);
        }
      }
    }
    return fullItems;
  }

  async #toItemData(vaultId, fullItem) {
    try {
      const itemData = {
        id: fullItem.id,
        title: fullItem.title,
        category: fullItem.category,
        vaultId: fullItem.vaultId,
        fields: (fullItem.fields || []).map(normalizeSourceField),
        sections: fullItem.sections || [],
        tags: fullItem.tags || [],
        websites: fullItem.urls || fullItem.websites || fullItem.websiteUrls || [],
        notes: fullItem.notes || ""
      };
      if (DEBUG_ENABLED) {
        logger.info(vaultId, `[DEBUG] Processed "${itemData.title}" [${itemData.id}], category: "${itemData.category}", fields after normalization: ${JSON.stringify(redactFieldsForLog(itemData.fields))}`);
      }

      if (fullItem.files && fullItem.files.length > 0) {
        const files = await mapWithConcurrency(fullItem.files, FILES_PER_ITEM_CONCURRENCY, (file) =>
          this.retry(() => this.client.items.files.read(vaultId, fullItem.id, file.attributes))
            .then(fileContent => ({
              name: file.attributes.name,
              content: fileContent,
              sectionId: file.sectionId,
              fieldId: file.fieldId
            }))
            .catch(err => {
              logger.warning(vaultId, `Failed to read file ${file.attributes.name}: ${err.message}`);
              return null;
            })
        );
        itemData.files = files.filter(f => f !== null);
      }

      if (fullItem.category === sdk.ItemCategory.Document && fullItem.document) {
        try {
          const documentContent = await this.retry(() =>
            this.client.items.files.read(vaultId, fullItem.id, fullItem.document)
          );
          itemData.document = {
            name: fullItem.document.name,
            content: documentContent instanceof Uint8Array ? documentContent : new Uint8Array(documentContent)
          };
        } catch (docError) {
          logger.warning(vaultId, `Failed to read document for ${fullItem.title}: ${docError.message}`);
        }
      }

      return itemData;
    } catch (processError) {
      logger.error(vaultId, `Failed to process item ${fullItem.id}: ${processError.message}`);
      if (DEBUG_ENABLED) {
        logger.error(vaultId, `[DEBUG] Processing FAILED for item "${fullItem.title}" [${fullItem.id}]: ${formatErrorForLog(processError)}`);
      }
      return null;
    }
  }
}

function normalizeSourceField(field) {
  if (field.fieldType === sdk.ItemFieldType.Address && field.details?.content) {
    return {
      ...field,
      details: {
        content: {
          street: field.details.content.street || "",
          city: field.details.content.city || "",
          state: field.details.content.state || "",
          zip: field.details.content.zip || "",
          country: field.details.content.country || ""
        }
      }
    };
  } else if (field.fieldType === sdk.ItemFieldType.SshKey && field.details?.content) {
    return {
      ...field,
      details: {
        content: {
          privateKey: field.details.content.privateKey || field.value || "",
          publicKey: field.details.content.publicKey || "",
          fingerprint: field.details.content.fingerprint || "",
          keyType: field.details.content.keyType || ""
        }
      }
    };
  } else if (field.fieldType === sdk.ItemFieldType.Totp) {
    return {
      ...field,
      value: field.details?.content?.totp || field.value || "",
      details: field.details || {}
    };
  }
  return field;
}
const attrs = [{ name: 'commonName', value: 'localhost' }];
const opts = { keySize: 2048, algorithm: 'sha256', days: 365 };

try {
  const pems = await selfsigned.generate(attrs, opts);
  const options = { key: pems.private, cert: pems.cert };

  https.createServer(options, app).listen(PORT, HOST, () => {
    console.log(`
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   1Password Vault Migration Tool v2.1                         ║
║   Server started successfully on ${HOST}:${PORT}
║   Access at: https://localhost:${PORT}
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
    `);
    logger.info(null, `Server started on ${HOST}:${PORT} (log file: ${logger.logPath})`);
  });
} catch (error) {
  console.error('Fatal error starting server:', error);
  logger.error(null, `Fatal error starting server: ${error.message}`);
  process.exit(1);
}
