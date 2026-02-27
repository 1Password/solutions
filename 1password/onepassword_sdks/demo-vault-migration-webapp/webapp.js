import sdk from '@1password/sdk';
import { execFileSync } from 'child_process';
import crypto from 'crypto';

// Migration sessions — stores credentials in memory, keyed by short-lived session ID.
// Prevents tokens from appearing in URLs or browser history.
const migrationSessions = new Map();
const SESSION_TTL = 5 * 60 * 1000; // 5 minutes
import express from 'express';
import bodyParser from 'body-parser';
import path from 'path';
import { fileURLToPath } from 'url';
import https from 'https';
import selfsigned from 'selfsigned';
import fs from 'fs';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// .env loading (local node only). 1Password Environments triggers auth prompt on read.
// Vars: AUTH_MODE, SOURCE_TOKEN, DEST_TOKEN, SOURCE_ACCOUNT, DEST_ACCOUNT

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
    console.log(`[startup] .env parsed — found keys: ${varKeys.join(', ')}`);

    envConfig.loaded = true;
    envConfig.authMode = vars.AUTH_MODE || null;
    envConfig.sourceToken = vars.SOURCE_TOKEN || null;
    envConfig.destToken = vars.DEST_TOKEN || null;
    envConfig.sourceAccount = vars.SOURCE_ACCOUNT || null;
    envConfig.destAccount = vars.DEST_ACCOUNT || null;

    const VALID_AUTH_MODES = ['service-account', 'desktop'];
    if (envConfig.authMode && !VALID_AUTH_MODES.includes(envConfig.authMode)) {
      console.log(`[startup] Auth mode: invalid value (not 'service-account' or 'desktop') — falling back to auto-detect`);
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
      console.log(`[startup] No .env file found — manual token entry mode`);
    } else {
      console.warn(`[startup] Could not read .env file: ${err.message}`);
    }
    return false;
  }
}
loadEnvFile();

const app = express();
class LogManager {
  constructor() {
    this.globalLog = [];
    this.vaultLogs = {};
    this.errorCount = 0;
    this.warningCount = 0;
    this.failedItems = [];
    this.failedVaults = [];
    this.vaultSummaries = {};
  }

  log(level, vaultId, message, metadata = {}) {
    const timestamp = new Date().toISOString();
    const entry = { timestamp, level, vaultId, message, ...metadata };
    this.globalLog.push(entry);
    if (vaultId) {
      (this.vaultLogs[vaultId] ??= []).push(entry);
    }
    if (level === 'ERROR') this.errorCount++;
    if (level === 'WARNING') this.warningCount++;
    const prefix = `[${timestamp}] [${level}]${vaultId ? ` [${vaultId}]` : ''}`;
    console.log(`${prefix} ${message}`);
  }

  info(vaultId, message, metadata = {}) { this.log('INFO', vaultId, message, metadata); }
  warning(vaultId, message, metadata = {}) { this.log('WARNING', vaultId, message, metadata); }
  error(vaultId, message, metadata = {}) { this.log('ERROR', vaultId, message, metadata); }

  logFailedItem(vaultId, vaultName, itemId, itemTitle, error) {
    this.failedItems.push({
      vaultId, vaultName, itemId, itemTitle,
      error: error.message || error.toString(),
      timestamp: new Date().toISOString()
    });
    this.error(vaultId, `Failed to migrate item [${itemId}] "${itemTitle}": ${error.message}`, {
      itemId, itemTitle, errorMessage: error.message
    });
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

  getGlobalLog() {
    return this.globalLog.map(e =>
      `[${e.timestamp}] [${e.level}]${e.vaultId ? ` [Vault: ${e.vaultId}]` : ''}${e.itemId ? ` [Item: ${e.itemId}]` : ''} ${e.message}`
    ).join('\n');
  }

  getVaultLog(vaultId) {
    if (!this.vaultLogs[vaultId]) return '';
    return this.vaultLogs[vaultId].map(e =>
      `[${e.timestamp}] [${e.level}]${e.itemId ? ` [Item: ${e.itemId}]` : ''} ${e.message}`
    ).join('\n');
  }

  getSummary() {
    return {
      totalEntries: this.globalLog.length,
      errors: this.errorCount,
      warnings: this.warningCount,
      vaults: Object.keys(this.vaultLogs).length,
      failedItems: this.failedItems.length,
      failedVaults: this.failedVaults.length
    };
  }

  getFailureSummary() {
    const hasFailedItems = this.failedItems.length > 0;
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
      summary += `FAILED ITEMS SUMMARY (${this.failedItems.length} total failures)\n`;
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
    this.globalLog = [];
    this.vaultLogs = {};
    this.errorCount = 0;
    this.warningCount = 0;
    this.failedItems = [];
    this.failedVaults = [];
    this.vaultSummaries = {};
  }
}

const logger = new LogManager();
app.set('views', path.join(__dirname, 'views'));
app.set('view engine', 'ejs');
app.use(express.static('public'));
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());
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
  const sensitiveLabels = /private.?key|secret|password|passphrase|credential|token|api.?key|ssh.?key|card.?number|ccnum|cvv|security.?code/i;
  
  const sensitiveFieldIds = /^(ccnum|cvv|cardNumber)$/;
  
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
    const isConcealed = f.fieldType === 'Concealed' || f.fieldType === sdk.ItemFieldType.Concealed;
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

const APP_LOCKED_PATTERNS = [
  'app is locked',
  'vault is locked',
  'not authorized',
  'biometric',
  'authentication required',
  'user interaction required',
  'locked',
  'sign-in required',
  'session expired',
  'connect to 1password',
  'refused',
  'unavailable',
];

function isAppLockedError(error) {
  const msg = (error.message || '').toLowerCase();
  return APP_LOCKED_PATTERNS.some(p => msg.includes(p));
}

const retryWithBackoff = async (fn, maxRetries = 3, baseDelay = 1000) => {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      
      if (isAppLockedError(error)) {
        logger.warning(null, `1Password app appears locked: "${error.message}" — waiting for unlock (attempt ${attempt})...`);
        
        const pollInterval = 5000;
        const maxWait = 5 * 60 * 1000;
        const start = Date.now();
        let unlocked = false;

        while (Date.now() - start < maxWait) {
          await new Promise(resolve => setTimeout(resolve, pollInterval));
          try {
            const result = await fn();
            unlocked = true;
            logger.info(null, `1Password app unlocked — resuming after ${Math.round((Date.now() - start) / 1000)}s`);
            return result;
          } catch (retryErr) {
            if (isAppLockedError(retryErr)) {
              if ((Date.now() - start) % 30000 < pollInterval) {
                logger.info(null, `Still waiting for 1Password unlock... (${Math.round((Date.now() - start) / 1000)}s elapsed)`);
              }
            } else {
              throw retryErr;
            }
          }
        }

        if (!unlocked) {
          logger.error(null, `Timed out waiting for 1Password app to unlock after 5 minutes`);
          throw new Error(`1Password app locked for over 5 minutes — migration paused. Unlock the app and try again.`);
        }
      }
      const isRateLimit = error.message.includes('rate limit') || error.message.includes('429') || error.message.includes('too many requests');
      const isDataConflict = error.message.includes('data conflict');

      if ((isRateLimit || isDataConflict) && attempt < maxRetries) {
        const delay = isRateLimit
          ? 30000 * Math.pow(2, attempt - 1)
          : baseDelay * Math.pow(2, attempt - 1);
        logger.warning(null, `Retrying attempt ${attempt} after ${delay}ms due to ${error.message}`);
        await new Promise(resolve => setTimeout(resolve, delay));
      } else {
        throw error;
      }
    }
  }
};
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
  logger.info(null, `Env reload complete — loaded: ${envConfig.loaded}, mode: ${envConfig.authMode || 'none'}, ready: ${ready}`);
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

    const vaultsWithCounts = [];
    const CONCURRENCY = 10;

    for (let i = 0; i < vaults.length; i += CONCURRENCY) {
      const batch = vaults.slice(i, i + CONCURRENCY);
      const batchResults = await Promise.all(batch.map(async (vault) => {
        try {
          const count = await getVaultItemCount(vault.id, sdkInstance, { skipArchived: true });
          logger.info(vault.id, `Vault ${vault.name}: ${count} items (type: ${vault.vaultType})`);
          return { ...vault, itemCount: count };
        } catch (error) {
          logger.error(vault.id, `Failed to get item count: ${error.message}`);
          return { ...vault, itemCount: 0 };
        }
      }));
      vaultsWithCounts.push(...batchResults);
    }

    res.json({ success: true, vaults: vaultsWithCounts });
  } catch (error) {
    logger.error(null, `Failed to list vaults: ${error.message}`);
    res.status(500).json({ success: false, error: error.message });
  }
});

let isMigrationCancelled = false;

app.post('/migration/cancel', (req, res) => {
  isMigrationCancelled = true;
  logger.info(null, 'Migration cancellation requested');
  res.json({ success: true, message: 'Migration cancellation requested' });
});


app.post('/migration/rate-limit-check', (req, res) => {
  const { vaultItemCounts } = req.body;
  if (!vaultItemCounts || !Array.isArray(vaultItemCounts)) {
    return res.json({ success: false, error: 'vaultItemCounts array required' });
  }
  const sanitized = vaultItemCounts.map(n => typeof n === 'number' && isFinite(n) ? Math.max(0, Math.floor(n)) : 0);
  const estimatedCalls = rateLimitTracker.estimateCalls(sanitized);
  const status = rateLimitTracker.getStatus(estimatedCalls);
  logger.info(null, `Rate limit check: estimated ${estimatedCalls} calls, ${status.used} used in last hour, ${status.remaining} remaining`);
  res.json({ success: true, ...status });
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
    const activeItems = await sdkInstance.client.items.list(vaultId);
    const activeCount = activeItems.length;

    if (!skipArchived) {
      try {
        const archivedItems = await sdkInstance.client.items.list(vaultId, {
          type: "ByState",
          content: { active: false, archived: true }
        });
        if (archivedItems.length > 0) {
          logger.info(vaultId, `Contains ${archivedItems.length} archived items`);
        }
      } catch (archiveError) {
        logger.warning(vaultId, `Could not fetch archived items: ${archiveError.message}`);
      }
    }

    return activeCount;
  } catch (error) {
    logger.error(vaultId, `Error fetching item count: ${error.message}`);
    return 0;
  }
}

const BATCH_SIZE = 100;

const RATE_LIMIT_WINDOW = 60 * 60 * 1000; 
const RATE_LIMIT_MAX = 1000;

const rateLimitTracker = {
  calls: [],

  record() {
    this.calls.push(Date.now());
    this.prune();
  },

  recordN(n) {
    const now = Date.now();
    for (let i = 0; i < n; i++) this.calls.push(now);
    this.prune();
  },

  prune() {
    const cutoff = Date.now() - RATE_LIMIT_WINDOW;
    this.calls = this.calls.filter(t => t > cutoff);
  },

  getUsed() {
    this.prune();
    return this.calls.length;
  },

  getRemaining() {
    return Math.max(0, RATE_LIMIT_MAX - this.getUsed());
  },
  
  estimateCalls(vaultItemCounts) {
    let total = 0;
    for (const count of vaultItemCounts) {
      if (count === 0) { total += 1; continue; }
      const vaultCreate = 1;
      const individualEstimate = Math.ceil(count * 0.1);
      const batchableEstimate = count - individualEstimate;
      const batchCalls = Math.ceil(batchableEstimate / BATCH_SIZE);
      const refUpdateEstimate = Math.ceil(count * 0.05); 
      total += vaultCreate + batchCalls + individualEstimate + refUpdateEstimate;
    }
    return total;
  },

  getStatus(estimatedCalls) {
    const used = this.getUsed();
    const remaining = this.getRemaining();
    const willExceed = estimatedCalls > remaining;
    const minutesUntilReset = this.calls.length > 0
      ? Math.ceil((this.calls[0] + RATE_LIMIT_WINDOW - Date.now()) / 60000)
      : 0;

    return {
      used,
      remaining,
      estimatedCalls,
      willExceed,
      minutesUntilReset: Math.max(0, minutesUntilReset),
    };
  }
};

async function desktopReadAllVaults(sourceSDK, vaultsToRead, isCancelled, onProgress = null) {
  const vaultData = [];

  for (const vault of vaultsToRead) {
    if (isCancelled()) break;

    logger.info(vault.id, `[Desktop Phase 1] Reading vault "${vault.name}"`);

    try {
      const sourceItemCount = await getVaultItemCount(vault.id, sourceSDK, { skipArchived: true });
      const items = await sourceSDK.listVaultItems(vault.id);
      logger.info(vault.id, `[Desktop Phase 1] Read ${items.length} items from "${vault.name}"`);

      for (const item of items) {
        if (item.category === 'Document' || item.category === sdk.ItemCategory.Document) {
          try {
            const fullItem = await retryWithBackoff(() => sourceSDK.client.items.get(vault.id, item.id));
            if (fullItem.category === sdk.ItemCategory.Document && fullItem.document) {
              const documentContent = await retryWithBackoff(() =>
                sourceSDK.client.items.files.read(vault.id, item.id, fullItem.document)
              );
              item.document = {
                name: fullItem.document.name,
                content: documentContent instanceof Uint8Array ? documentContent : new Uint8Array(documentContent)
              };
            }
          } catch (docError) {
            logger.warning(vault.id, `[Desktop Phase 1] Document fetch failed for "${item.title}": ${docError.message}`);
          }
        }

        if (item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard) {
          try {
            const fullItem = await retryWithBackoff(() => sourceSDK.client.items.get(vault.id, item.id));
            item.fields = fullItem.fields;

            const expiryField = item.fields?.find(f => f.id === 'expiry');
            if (expiryField && (!expiryField.value || expiryField.fieldType === 'Unsupported')) {
              try {
                const cliOutput = execFileSync('op', ['item', 'get', item.id, '--vault', vault.id, '--format', 'json'], { encoding: 'utf8' });
                const cliItem = JSON.parse(cliOutput);
                const cliExpiryField = cliItem.fields?.find(f => f.id === 'expiry');
                if (cliExpiryField && cliExpiryField.value) {
                  expiryField.value = cliExpiryField.value;
                  expiryField.fieldType = sdk.ItemFieldType.MonthYear;
                  logger.info(vault.id, `[Desktop Phase 1] Recovered expiry via CLI: ${cliExpiryField.value}`);
                }
              } catch (cliError) {
                logger.warning(vault.id, `[Desktop Phase 1] CLI expiry fallback failed: ${cliError.message}`);
              }
            }
          } catch (ccError) {
            logger.warning(vault.id, `[Desktop Phase 1] Credit card fetch failed for "${item.title}": ${ccError.message}`);
          }
        }
      }

      vaultData.push({ vaultId: vault.id, vaultName: vault.name, vaultType: vault.vaultType || 'shared', items, sourceItemCount, suffix: vault.suffix || '' });
    } catch (error) {
      logger.error(vault.id, `[Desktop Phase 1] Failed to read vault "${vault.name}": ${error.message}`);
      logger.logFailedVault(vault.id, vault.name, error);
      vaultData.push({ vaultId: vault.id, vaultName: vault.name, vaultType: vault.vaultType || 'shared', items: [], sourceItemCount: 0, error: error.message, suffix: vault.suffix || '' });
    }
  }

  return vaultData;
}

async function desktopWriteVault(vaultData, destSDK, destAccountName, isCancelled, onProgress = null, suffix = '') {
  const { vaultId, vaultName, items, sourceItemCount, vaultType } = vaultData;
  const isPersonal = vaultType === 'personal';

  logger.info(vaultId, `[Desktop Phase 2] Writing vault "${vaultName}" (${items.length} items, type: ${vaultType})`);

  let newVaultId;

  if (isPersonal) {
    logger.info(vaultId, `[Desktop Phase 2] Personal vault — looking for existing Private vault on destination`);
    try {
      const destVaults = await destSDK.listVaults();
      const privateVault = destVaults.find(v => v.vaultType === 'personal');
      if (privateVault) {
        newVaultId = privateVault.id;
        logger.info(vaultId, `[Desktop Phase 2] Found destination Private vault: "${privateVault.name}" [${newVaultId}]`);
      } else {
        const byName = destVaults.find(v => {
          const n = (v.name || '').toLowerCase();
          return n === 'private' || n === 'employee' || n.includes('employee vault');
        });
        if (byName) {
          newVaultId = byName.id;
          logger.info(vaultId, `[Desktop Phase 2] Found destination Private vault by name: "${byName.name}" [${newVaultId}]`);
        } else {
          throw new Error('Could not find a Private/Employee vault on the destination account');
        }
      }
    } catch (error) {
      logger.error(vaultId, `[Desktop Phase 2] Failed to find destination Private vault: ${error.message}`);
      throw new Error(`Could not find destination Private vault: ${error.message}`);
    }
  } else {
    const destVaultName = suffix ? `${vaultName} (Migrated - ${suffix})` : `${vaultName} (Migrated)`;
    try {
      const args = ['vault', 'create', destVaultName, '--format', 'json'];
      if (destAccountName) args.push('--account', destAccountName);
      const newVaultOutput = execFileSync('op', args, { env: { ...process.env }, encoding: 'utf8' });
      const newVault = JSON.parse(newVaultOutput);
      newVaultId = newVault.id;
      rateLimitTracker.record();
      logger.info(vaultId, `[Desktop Phase 2] Created dest vault "${destVaultName}" [${newVaultId}]`);
    } catch (error) {
      logger.error(vaultId, `[Desktop Phase 2] Failed to create vault: ${error.message}`);
      throw new Error(`Vault creation failed: ${error.message}`);
    }
  }

  if (items.length === 0) {
    return { itemsLength: 0, migrationResults: [], sourceItemCount, destItemCount: 0, successCount: 0, failureCount: 0 };
  }

  const migrationResults = [];
  let processedItems = 0;
  let successCount = 0;
  let failureCount = 0;
  const idMap = new Map();
  const itemsWithRefs = [];

  const batchableItems = [];
  const individualItems = [];

  for (const item of items) {
    try {
      const categoryStr = String(item.category);
      logger.info(vaultId, `Item "${item.title}" category: ${categoryStr}`);
      const newItem = buildNewItem(item, newVaultId, vaultId);

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

      const isCreditCard = item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard;
      const hasBinary = !!(item.document || (item.files && item.files.length > 0));
      const needsIndividualCreate = hasBinary || isCreditCard;

      const entry = { sourceId: item.id, sourceTitle: item.title, sourceCategory: item.category, newItem, refFields, hasBinary: needsIndividualCreate };

      if (needsIndividualCreate) {
        individualItems.push(entry);
      } else {
        batchableItems.push(entry);
      }
    } catch (error) {
      processedItems++;
      failureCount++;
      logger.logFailedItem(vaultId, vaultName, item.id, item.title, error);
      migrationResults.push({ id: item.id, title: item.title, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
    }
  }
  logger.info(vaultId, `[Desktop Phase 2] Creating items (${batchableItems.length} batchable, ${individualItems.length} individual)...`);
  for (let i = 0; i < batchableItems.length; i += BATCH_SIZE) {
    if (isCancelled()) break;

    const chunk = batchableItems.slice(i, i + BATCH_SIZE);
    const itemsForBatch = chunk.map(entry => entry.newItem);

    try {
      const batchResponse = await retryWithBackoff(() =>
        destSDK.client.items.createAll(newVaultId, itemsForBatch)
      );
      rateLimitTracker.record();

      for (let j = 0; j < batchResponse.individualResponses.length; j++) {
        const res = batchResponse.individualResponses[j];
        const entry = chunk[j];
        processedItems++;

        if (res.content) {
          idMap.set(entry.sourceId, res.content.id);
          successCount++;
          logger.info(vaultId, `Batch created item [${entry.sourceId}] "${entry.sourceTitle}" → ${res.content.id}`, { itemId: entry.sourceId });
          migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: true, progress: (processedItems / items.length) * 100 });
          if (entry.refFields.length > 0) {
            itemsWithRefs.push({ sourceItemId: entry.sourceId, destItemId: res.content.id, refFields: entry.refFields });
          }
        } else if (res.error) {
          failureCount++;
          const errMsg = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
          logger.error(vaultId, `Batch create failed for "${entry.sourceTitle}" [${entry.sourceId}]: ${errMsg}`);
          logger.logFailedItem(vaultId, vaultName, entry.sourceId, entry.sourceTitle, new Error(errMsg));
          migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: false, error: errMsg, progress: (processedItems / items.length) * 100 });
        }
      }
    } catch (error) {
      for (const entry of chunk) {
        processedItems++;
        failureCount++;
        logger.logFailedItem(vaultId, vaultName, entry.sourceId, entry.sourceTitle, error);
        migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
      }
    }

    if (onProgress) onProgress(processedItems, items.length, successCount, failureCount);
  }
  for (const entry of individualItems) {
    if (isCancelled()) break;

    try {
      const createdItem = await retryWithBackoff(() => destSDK.client.items.create(entry.newItem));
      rateLimitTracker.record();
      idMap.set(entry.sourceId, createdItem.id);
      processedItems++;
      successCount++;
      logger.info(vaultId, `Created item [${entry.sourceId}] "${entry.sourceTitle}" → ${createdItem.id}`, { itemId: entry.sourceId });
      migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: true, progress: (processedItems / items.length) * 100 });
      if (entry.refFields.length > 0) {
        itemsWithRefs.push({ sourceItemId: entry.sourceId, destItemId: createdItem.id, refFields: entry.refFields });
      }
    } catch (error) {
      processedItems++;
      failureCount++;
      logger.error(vaultId, `Failed to create item "${entry.sourceTitle}" [${entry.sourceId}]: ${error.message}`);
      logger.logFailedItem(vaultId, vaultName, entry.sourceId, entry.sourceTitle, error);
      migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
    }

    if (onProgress) onProgress(processedItems, items.length, successCount, failureCount);
  }

  if (itemsWithRefs.length > 0) {
    logger.info(vaultId, `[Desktop Phase 2] Adding reference fields to ${itemsWithRefs.length} items`);
    for (const ref of itemsWithRefs) {
      try {
        const destItem = await retryWithBackoff(() => destSDK.client.items.get(newVaultId, ref.destItemId));
        let updated = false;
        for (const refField of ref.refFields) {
          const newRefId = idMap.get(refField.sourceRefId);
          if (newRefId) {
            if (!destItem.fields) destItem.fields = [];
            destItem.fields.push({
              id: refField.fieldId,
              title: refField.title || "Reference",
              fieldType: sdk.ItemFieldType.Reference,
              value: newRefId,
              ...(refField.sectionId ? { sectionId: refField.sectionId } : {})
            });
            if (refField.sectionId && destItem.sections) {
              if (!destItem.sections.some(s => s.id === refField.sectionId)) {
                destItem.sections.push({ id: refField.sectionId, title: refField.sectionId });
              }
            }
            updated = true;
          }
        }
        if (updated) {
          await retryWithBackoff(() => destSDK.client.items.put(destItem));
          rateLimitTracker.record();
        }
      } catch (error) {
        logger.warning(vaultId, `[Desktop Phase 2] Failed to add references for ${ref.destItemId}: ${error.message}`);
      }
    }
  }

  const destItemCount = await getVaultItemCount(newVaultId, destSDK, { skipArchived: true });
  logger.info(vaultId, `[Desktop Phase 2] Vault "${vaultName}" complete: ${successCount}/${items.length} items`);

  return { itemsLength: items.length, migrationResults, sourceItemCount, destItemCount, successCount, failureCount };
}

async function migrateVault(vaultId, vaultName, sourceToken, destToken, sourceSDK, destSDK, isCancelled, onProgress = null, authMode = 'service-account', destAccountName = null, suffix = '') {
  logger.info(vaultId, `Starting migration for vault ${vaultName}`);

  const sourceItemCount = await getVaultItemCount(vaultId, sourceSDK, { skipArchived: true });
  logger.info(vaultId, `Source item count: ${sourceItemCount}`);

  const destVaultName = suffix ? `${vaultName} (Migrated - ${suffix})` : `${vaultName} (Migrated)`;

  let newVaultId;
  try {
    const cliEnv = { ...process.env };
    const args = ['vault', 'create', destVaultName, '--format', 'json'];

    if (authMode === 'desktop') {
      if (destAccountName) args.push('--account', destAccountName);
    } else {
      cliEnv.OP_SERVICE_ACCOUNT_TOKEN = destToken;
    }

    const newVaultOutput = execFileSync('op', args, { env: cliEnv, encoding: 'utf8' });
    const newVault = JSON.parse(newVaultOutput);
    newVaultId = newVault.id;
    rateLimitTracker.record();
    logger.info(vaultId, `Created destination vault "${destVaultName}" [${newVaultId}]`);
  } catch (error) {
    logger.error(vaultId, `Failed to create destination vault: ${error.message}`);
    throw new Error(`Vault creation failed: ${error.message}`);
  }

  let items;
  try {
    items = await sourceSDK.listVaultItems(vaultId);
    logger.info(vaultId, `Found ${items.length} items to migrate`);
  } catch (error) {
    logger.error(vaultId, `Failed to list items: ${error.message}`);
    throw new Error(`Item listing failed: ${error.message}`);
  }

  if (isCancelled()) {
    logger.info(vaultId, `Migration cancelled by user`);
    return { itemsLength: items.length, migrationResults: [], sourceItemCount, destItemCount: null, successCount: 0, failureCount: 0 };
  }

  const migrationResults = [];
  let processedItems = 0;
  let successCount = 0;
  let failureCount = 0;

  const idMap = new Map();
  const itemsWithRefs = [];

  logger.info(vaultId, `Phase 1: Building item objects...`);

  const batchableItems = [];
  const individualItems = [];

  for (const item of items) {
    try {
      const categoryStr = String(item.category);
      logger.info(vaultId, `Item "${item.title}" category: ${categoryStr}`);
      if (DEBUG_ENABLED) {
        logger.info(vaultId, `[DEBUG] Source item "${item.title}" [${item.id}] — category: "${item.category}"`);
        logger.info(vaultId, `[DEBUG] Source fields (${item.fields?.length || 0}): ${JSON.stringify(redactFieldsForLog(item.fields || []))}`);
        logger.info(vaultId, `[DEBUG] Source sections (${item.sections?.length || 0}): ${JSON.stringify(item.sections || [])}`);
        logger.info(vaultId, `[DEBUG] Source websites: ${JSON.stringify(item.websites || [])}`);
        logger.info(vaultId, `[DEBUG] Source tags: ${JSON.stringify(item.tags || [])}`);
        logger.info(vaultId, `[DEBUG] Source files: ${(item.files || []).map(f => f.name).join(', ') || 'none'}`);
        logger.info(vaultId, `[DEBUG] Source notes present: ${!!(item.notes && item.notes.trim())}`);
      }

      if (item.category === 'Document' || item.category === sdk.ItemCategory.Document) {
        try {
          const fullItem = await retryWithBackoff(() => sourceSDK.client.items.get(vaultId, item.id));
          if (fullItem.category === sdk.ItemCategory.Document && fullItem.document) {
            const documentContent = await retryWithBackoff(() =>
              sourceSDK.client.items.files.read(vaultId, item.id, fullItem.document)
            );
            item.document = {
              name: fullItem.document.name,
              content: documentContent instanceof Uint8Array ? documentContent : new Uint8Array(documentContent)
            };
          }
        } catch (docError) {
          logger.warning(vaultId, `Document handling failed for ${item.title}: ${docError.message}`);
        }
      }

      if (item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard) {
        try {
          const fullItem = await retryWithBackoff(() => sourceSDK.client.items.get(vaultId, item.id));
          item.fields = fullItem.fields;

          const expiryField = item.fields?.find(f => f.id === 'expiry');
          if (expiryField && (!expiryField.value || expiryField.fieldType === 'Unsupported')) {
            try {
              const sourceEnv = { ...process.env, OP_SERVICE_ACCOUNT_TOKEN: sourceToken };
              const cliOutput = execFileSync('op', ['item', 'get', item.id, '--vault', vaultId, '--format', 'json'], { env: sourceEnv, encoding: 'utf8' });
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
              logger.warning(vaultId, `CLI fallback for expiry failed: ${cliError.message}`);
            }
          }
        } catch (ccError) {
          logger.warning(vaultId, `Credit card field fetch failed for ${item.title}: ${ccError.message}`);
        }
      }

      const newItem = buildNewItem(item, newVaultId, vaultId);
      if (DEBUG_ENABLED) {
        logger.info(vaultId, `[DEBUG] Built dest item "${newItem.title}" — category: "${newItem.category}"`);
        logger.info(vaultId, `[DEBUG] Built dest fields (${newItem.fields?.length || 0}): ${JSON.stringify(redactFieldsForLog(newItem.fields || []))}`);
        logger.info(vaultId, `[DEBUG] Built dest sections (${newItem.sections?.length || 0}): ${JSON.stringify(newItem.sections || [])}`);
        logger.info(vaultId, `[DEBUG] Built dest vaultId: ${newItem.vaultId}`);
        logger.info(vaultId, `[DEBUG] Built dest websites: ${JSON.stringify(newItem.websites || [])}`);
        logger.info(vaultId, `[DEBUG] Built dest tags: ${JSON.stringify(newItem.tags || [])}`);
        logger.info(vaultId, `[DEBUG] Built dest notes present: ${!!(newItem.notes && newItem.notes.trim())}`);
        logger.info(vaultId, `[DEBUG] Built dest files: ${(newItem.files || []).map(f => f.name).join(', ') || 'none'}`);
        logger.info(vaultId, `[DEBUG] Built dest hasDocument: ${!!newItem.document}`);
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
            refFields.push({
              fieldId: field.id,
              title: field.title,
              sectionId: field.sectionId,
              sourceRefId: field._sourceRefId
            });
          } else {
            delete field._isReference;
            delete field._sourceRefId;
            fieldsWithoutRefs.push(field);
          }
        }
        newItem.fields = fieldsWithoutRefs;
      }

      const isCreditCard = item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard;
      const hasBinary = !!(item.document || (item.files && item.files.length > 0));
      const needsIndividualCreate = hasBinary || isCreditCard;

      const entry = { sourceId: item.id, sourceTitle: item.title, sourceCategory: item.category, newItem, refFields, hasBinary: needsIndividualCreate };

      if (needsIndividualCreate) {
        individualItems.push(entry);
      } else {
        batchableItems.push(entry);
      }
    } catch (error) {
      processedItems++;
      failureCount++;
      
      if (DEBUG_ENABLED) {
        logger.error(vaultId, `[DEBUG] Phase 1 build FAILED for "${item.title}" [${item.id}]: ${formatErrorForLog(error)}`);
      }
      logger.logFailedItem(vaultId, vaultName, item.id, item.title, error);
      migrationResults.push({ id: item.id, title: item.title, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
    }
  }

  logger.info(vaultId, `Phase 2: Creating items (${batchableItems.length} batchable, ${individualItems.length} individual)...`);
  for (let i = 0; i < batchableItems.length; i += BATCH_SIZE) {
    if (isCancelled()) {
      logger.info(vaultId, `Migration cancelled by user`);
      return { itemsLength: items.length, migrationResults, sourceItemCount, destItemCount: null, successCount, failureCount };
    }

    const chunk = batchableItems.slice(i, i + BATCH_SIZE);
    const itemsForBatch = chunk.map(entry => entry.newItem);
    for (const entry of chunk) {
      if (DEBUG_ENABLED) {
        logger.info(vaultId, `[DEBUG] About to batch-create "${entry.sourceTitle}" [${entry.sourceId}] — category in payload: "${entry.newItem.category}"`);
      }
    }

    try {
      const batchResponse = await retryWithBackoff(() =>
        destSDK.client.items.createAll(newVaultId, itemsForBatch)
      );
      rateLimitTracker.record();

      for (let j = 0; j < batchResponse.individualResponses.length; j++) {
        const res = batchResponse.individualResponses[j];
        const entry = chunk[j];
        processedItems++;

        if (res.content) {
          idMap.set(entry.sourceId, res.content.id);
          successCount++;
          migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: true, progress: (processedItems / items.length) * 100 });
          logger.info(vaultId, `Batch created item [${entry.sourceId}] "${entry.sourceTitle}" → ${res.content.id}`, { itemId: entry.sourceId });
          if (DEBUG_ENABLED) {
            logger.info(vaultId, `[DEBUG] Successfully batch-created "${entry.sourceTitle}" [${entry.sourceId}] → ${res.content.id}`);
          }
          if (entry.refFields.length > 0) {
            itemsWithRefs.push({ sourceItemId: entry.sourceId, destItemId: res.content.id, refFields: entry.refFields });
          }
        } else if (res.error) {
          failureCount++;
          const errMsg = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
          if (DEBUG_ENABLED) {
            logger.error(vaultId, `[DEBUG] Batch create FAILED for "${entry.sourceTitle}" [${entry.sourceId}]: ${formatErrorForLog(typeof res.error === 'object' ? res.error : { message: errMsg })}`);
            logger.error(vaultId, `[DEBUG] Raw batch error object: ${JSON.stringify(res.error)}`);
            logger.error(vaultId, `[DEBUG] Full payload that failed: ${JSON.stringify(sanitizeItemForLog(entry.newItem))}`);
          }

          logger.logFailedItem(vaultId, vaultName, entry.sourceId, entry.sourceTitle, new Error(errMsg));
          migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: false, error: errMsg, progress: (processedItems / items.length) * 100 });
        }
      }
    } catch (error) {
      const dbItemsInBatch = DEBUG_ENABLED ? chunk : [];
      if (dbItemsInBatch.length > 0) {
        logger.error(vaultId, `[DEBUG] Entire batch failed containing ${dbItemsInBatch.length} item(s): ${formatErrorForLog(error)}`);
        for (const dbEntry of dbItemsInBatch) {
          logger.error(vaultId, `[DEBUG] Item in failed batch: "${dbEntry.sourceTitle}" [${dbEntry.sourceId}] — payload: ${JSON.stringify(sanitizeItemForLog(dbEntry.newItem))}`);
        }
      }

      for (const entry of chunk) {
        processedItems++;
        failureCount++;
        logger.logFailedItem(vaultId, vaultName, entry.sourceId, entry.sourceTitle, error);
        migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
      }
    }

    if (onProgress) {
      onProgress(processedItems, items.length, successCount, failureCount);
    }
  }
  for (const entry of individualItems) {
    if (isCancelled()) {
      logger.info(vaultId, `Migration cancelled by user`);
      return { itemsLength: items.length, migrationResults, sourceItemCount, destItemCount: null, successCount, failureCount };
    }
    if (DEBUG_ENABLED) {
      logger.info(vaultId, `[DEBUG] About to individually create "${entry.sourceTitle}" [${entry.sourceId}] — category in payload: "${entry.newItem.category}"`);
      logger.info(vaultId, `[DEBUG] Individual create payload: ${JSON.stringify(sanitizeItemForLog(entry.newItem))}`);
    }

    try {
      const createdItem = await retryWithBackoff(() => destSDK.client.items.create(entry.newItem));
      rateLimitTracker.record();

      idMap.set(entry.sourceId, createdItem.id);
      processedItems++;
      successCount++;
      migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: true, progress: (processedItems / items.length) * 100 });
      logger.info(vaultId, `Created item [${entry.sourceId}] "${entry.sourceTitle}" → ${createdItem.id} (individual)`, { itemId: entry.sourceId });
      if (DEBUG_ENABLED) {
        logger.info(vaultId, `[DEBUG] Successfully individually created "${entry.sourceTitle}" [${entry.sourceId}] → ${createdItem.id}`);
      }

      if (entry.refFields.length > 0) {
        itemsWithRefs.push({ sourceItemId: entry.sourceId, destItemId: createdItem.id, refFields: entry.refFields });
      }
    } catch (error) {
      processedItems++;
      failureCount++;
      if (DEBUG_ENABLED) {
        logger.error(vaultId, `[DEBUG] Individual create FAILED for "${entry.sourceTitle}" [${entry.sourceId}]: ${formatErrorForLog(error)}`);
        logger.error(vaultId, `[DEBUG] Full payload that failed: ${JSON.stringify(sanitizeItemForLog(entry.newItem))}`);
      }

      logger.logFailedItem(vaultId, vaultName, entry.sourceId, entry.sourceTitle, error);
      migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
    }

    if (onProgress && (processedItems % 3 === 0 || processedItems === items.length)) {
      onProgress(processedItems, items.length, successCount, failureCount);
    }
  }
  if (itemsWithRefs.length > 0) {
    logger.info(vaultId, `Phase 3: Adding reference fields to ${itemsWithRefs.length} items...`);

    for (const ref of itemsWithRefs) {
      try {
        const destItem = await retryWithBackoff(() => destSDK.client.items.get(newVaultId, ref.destItemId));

        let updated = false;
        for (const refField of ref.refFields) {
          const newRefId = idMap.get(refField.sourceRefId);
          if (newRefId) {
            if (!destItem.fields) destItem.fields = [];
            destItem.fields.push({
              id: refField.fieldId,
              title: refField.title || "Reference",
              fieldType: sdk.ItemFieldType.Reference,
              value: newRefId,
              ...(refField.sectionId ? { sectionId: refField.sectionId } : {})
            });
            if (refField.sectionId && destItem.sections) {
              if (!destItem.sections.some(s => s.id === refField.sectionId)) {
                destItem.sections.push({ id: refField.sectionId, title: refField.sectionId });
              }
            }

            updated = true;
            logger.info(vaultId, `Added reference field "${refField.fieldId}" to item ${ref.destItemId}: ${refField.sourceRefId} → ${newRefId}`);
          } else {
            logger.warning(vaultId, `Reference target ${refField.sourceRefId} not found in ID map — referenced item may not have been migrated`);
          }
        }

        if (updated) {
          await retryWithBackoff(() => destSDK.client.items.put(destItem));
          rateLimitTracker.record();
          logger.info(vaultId, `Updated item ${ref.destItemId} with reference fields`);
        }
      } catch (error) {
        logger.warning(vaultId, `Failed to add references for item ${ref.destItemId}: ${error.message}`);
      }
    }
  } else {
    logger.info(vaultId, `Phase 3: No reference fields to remap`);
  }
  const destItemCount = await getVaultItemCount(newVaultId, destSDK, { skipArchived: true });
  logger.info(vaultId, `Destination item count: ${destItemCount}`);
  logger.info(vaultId, `Migration completed - Success: ${successCount}, Failed: ${failureCount}`);

  logger.logVaultComplete(vaultId, vaultName, { sourceItemCount, destItemCount, successCount, failureCount });

  if (sourceItemCount === destItemCount && failureCount === 0) {
    logger.info(vaultId, `Successfully migrated all ${sourceItemCount} items`);
  } else {
    logger.warning(vaultId, `Item count mismatch - Source: ${sourceItemCount}, Destination: ${destItemCount}, Failed: ${failureCount}`);
  }

  return { itemsLength: items.length, migrationResults, sourceItemCount, destItemCount, successCount, failureCount };
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

    const result = await migrateVault(vaultId, vaultName, sourceToken, destToken, sourceSDK, destSDK, () => isMigrationCancelled, null, authMode, destAccountName);
    const { itemsLength, migrationResults, sourceItemCount, destItemCount, successCount, failureCount } = result;

    if (failureCount > 0 || sourceItemCount !== destItemCount) {
      res.json({
        success: false,
        message: `Vault "${vaultName}" migration completed with ${failureCount} failures out of ${itemsLength} items`,
        results: migrationResults,
        stats: { successCount, failureCount, sourceItemCount, destItemCount }
      });
    } else {
      res.json({
        success: true,
        message: `Successfully migrated vault "${vaultName}" with ${itemsLength} items`,
        results: migrationResults,
        stats: { successCount, failureCount, sourceItemCount, destItemCount }
      });
    }
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
  ) : null;

  const sessionId = crypto.randomUUID();
  migrationSessions.set(sessionId, {
    sourceToken: typeof sourceToken === 'string' ? sourceToken : null,
    destToken: typeof destToken === 'string' ? destToken : null,
    authMode: validatedMode,
    sourceAccountName: typeof sourceAccountName === 'string' ? sourceAccountName : '',
    destAccountName: typeof destAccountName === 'string' ? destAccountName : '',
    useEnv: useEnv === true || useEnv === 'true' ? 'true' : null,
    vaults: validatedVaults,
    createdAt: Date.now()
  });

  setTimeout(() => migrationSessions.delete(sessionId), SESSION_TTL);

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

  migrationSessions.delete(sessionId);

  const { sourceToken, destToken, authMode, sourceAccountName, destAccountName, useEnv, vaults } = session;
  let selectedVaults;

  try {
    selectedVaults = vaults ? (typeof vaults === 'string' ? JSON.parse(vaults) : vaults) : null;
  } catch (error) {
    selectedVaults = null;
  }
  let mode, resolvedSourceToken, resolvedDestToken, resolvedSourceAccount, resolvedDestAccount;

  if (useEnv === 'true' && envConfig.loaded) {
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

  if (mode !== 'desktop' && !resolvedSourceToken && !resolvedDestToken) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.flushHeaders();
    res.write(`data: ${JSON.stringify({ success: false, message: 'Source token and destination token are required', finished: true })}\n\n`);
    res.end();
    return;
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('Access-Control-Allow-Origin', req.headers.origin || 'https://localhost:3001');
  res.flushHeaders();

  const keepAliveInterval = setInterval(() => {
    try { res.write(': keep-alive\n\n'); } catch (e) { /* client disconnected */ }
  }, 15000);
  isMigrationCancelled = false;
  logger.info(null, `Starting bulk vault migration (mode: ${mode})`);
  let clientConnected = true;
  res.on('close', () => {
    clientConnected = false;
    clearInterval(keepAliveInterval);
    logger.info(null, 'Client disconnected from SSE — migration will continue on server');
  });
  function sseWrite(data) {
    if (!clientConnected) return;
    try { res.write(data); } catch (e) { clientConnected = false; }
  }
  try {
    
    if (mode === 'desktop') {

      sseWrite(`data: ${JSON.stringify({
        progress: 0,
        outcome: { phase: 'desktop-source-connect', message: `Connecting to source account "${resolvedSourceAccount}"...` }
      })}\n\n`);

      const sourceSDK = createSDKInstance('desktop', null, resolvedSourceAccount);
      await sourceSDK.initializeClient();

      let vaultsToMigrate;
      if (selectedVaults && selectedVaults.length > 0) {
        vaultsToMigrate = selectedVaults.map(v => ({ id: v.vaultId, name: v.vaultName, vaultType: v.vaultType || 'shared', suffix: v.suffix || '' }));
      } else {
        const allVaults = await sourceSDK.listVaults();
        vaultsToMigrate = allVaults.map(v => ({ id: v.id, name: v.name, vaultType: v.vaultType || 'shared', suffix: '' }));
      }

      const totalVaults = vaultsToMigrate.length;

      sseWrite(`data: ${JSON.stringify({
        progress: 0,
        outcome: { phase: 'desktop-reading', message: `Reading ${totalVaults} vault(s) from source account...` }
      })}\n\n`);
      const allVaultData = await desktopReadAllVaults(sourceSDK, vaultsToMigrate, () => isMigrationCancelled, (vaultIdx) => {
        sseWrite(`data: ${JSON.stringify({
          progress: 0,
          outcome: { phase: 'desktop-reading', message: `Reading vault ${vaultIdx + 1}/${totalVaults}...` }
        })}\n\n`);
      });

      const totalItemsRead = allVaultData.reduce((sum, v) => sum + v.items.length, 0);
      logger.info(null, `[Desktop] Phase 1 complete: read ${totalItemsRead} items from ${totalVaults} vaults`);

      if (isMigrationCancelled) {
        sseWrite(`data: ${JSON.stringify({ success: false, message: 'Migration cancelled by user', finished: true })}\n\n`);
        clearInterval(keepAliveInterval);
        if (clientConnected) res.end();
        return;
      }

      sseWrite(`data: ${JSON.stringify({
        progress: 0,
        outcome: { phase: 'desktop-dest-connect', message: `Connecting to destination account "${resolvedDestAccount}"...` }
      })}\n\n`);

      const destSDK = createSDKInstance('desktop', null, resolvedDestAccount);
      await destSDK.initializeClient();

      sseWrite(`data: ${JSON.stringify({
        progress: 0,
        outcome: { phase: 'desktop-dest-connect', message: `Connected to "${resolvedDestAccount}" — starting migration...` }
      })}\n\n`);

      let completedVaults = 0;
      const migrationResults = [];

      for (const vaultData of allVaultData) {
        if (isMigrationCancelled) {
          sseWrite(`data: ${JSON.stringify({ success: false, message: 'Migration cancelled by user', results: migrationResults })}\n\n`);
          clearInterval(keepAliveInterval);
          if (clientConnected) res.end();
          return;
        }

        if (vaultData.error) {
          const outcome = {
            vaultId: vaultData.vaultId, vaultName: vaultData.vaultName, success: false,
            message: `Skipped — source read failed: ${vaultData.error}`, phase: 'failed',
            error: vaultData.error, sourceItemCount: vaultData.sourceItemCount || 0,
            failureCount: vaultData.sourceItemCount || 0, successCount: 0
          };
          migrationResults.push(outcome);
          completedVaults++;
          sseWrite(`data: ${JSON.stringify({ progress: (completedVaults / totalVaults) * 100, outcome })}\n\n`);
          continue;
        }

        sseWrite(`data: ${JSON.stringify({
          progress: (completedVaults / totalVaults) * 100,
          outcome: { vaultId: vaultData.vaultId, vaultName: vaultData.vaultName, phase: 'preparing', message: `Creating vault and writing items...` }
        })}\n\n`);

        try {
          const progressCallback = (itemsProcessed, totalItems, successCount, failureCount) => {
            const vaultProgress = itemsProcessed / totalItems;
            const overallProgress = ((completedVaults + vaultProgress) / totalVaults) * 100;
            sseWrite(`data: ${JSON.stringify({
              progress: overallProgress,
              outcome: {
                vaultId: vaultData.vaultId, vaultName: vaultData.vaultName, phase: 'migrating',
                message: `Writing items (${itemsProcessed}/${totalItems})...`,
                itemsProcessed, totalItems, successCount, failureCount
              }
            })}\n\n`);
          };

          const result = await desktopWriteVault(vaultData, destSDK, resolvedDestAccount, () => isMigrationCancelled, progressCallback, vaultData.suffix || '');
          const { itemsLength, migrationResults: vaultResults, sourceItemCount, destItemCount, successCount, failureCount } = result;

          const isPersonalVault = vaultData.vaultType === 'personal';
          const isSuccess = isPersonalVault
            ? (failureCount === 0 && successCount === itemsLength)
            : (failureCount === 0 && sourceItemCount === destItemCount);

          const outcome = {
            vaultId: vaultData.vaultId, vaultName: vaultData.vaultName,
            success: isSuccess,
            message: isSuccess
              ? `Successfully migrated vault "${vaultData.vaultName}" with ${itemsLength} items`
              : `Vault "${vaultData.vaultName}" completed with ${failureCount} failures out of ${itemsLength} items`,
            results: vaultResults, sourceItemCount, destItemCount, successCount, failureCount, phase: 'completed'
          };

          migrationResults.push(outcome);
          completedVaults++;
          sseWrite(`data: ${JSON.stringify({ progress: (completedVaults / totalVaults) * 100, outcome })}\n\n`);
        } catch (error) {
          logger.error(vaultData.vaultId, `[Desktop Phase 2] Vault write failed: ${error.message}`);
          logger.logFailedVault(vaultData.vaultId, vaultData.vaultName, error);
          const outcome = {
            vaultId: vaultData.vaultId, vaultName: vaultData.vaultName, success: false,
            message: `Failed: ${error.message}`, error: error.message, phase: 'failed'
          };
          migrationResults.push(outcome);
          completedVaults++;
          sseWrite(`data: ${JSON.stringify({ progress: (completedVaults / totalVaults) * 100, outcome })}\n\n`);
        }
      }
      const failedVaults = migrationResults.filter(r => !r.success);
      const summary = logger.getSummary();

      sseWrite(`data: ${JSON.stringify({
        success: failedVaults.length === 0,
        message: failedVaults.length === 0
          ? `Successfully migrated all ${totalVaults} vaults`
          : `Migration completed with ${failedVaults.length} vault failures out of ${totalVaults} vaults`,
        results: migrationResults, summary, finished: true
      })}\n\n`);

      clearInterval(keepAliveInterval);
      if (clientConnected) res.end();
      return;
    }

    const sourceSDK = createSDKInstance(mode, resolvedSourceToken, resolvedSourceAccount);
    await sourceSDK.initializeClient();
    const destSDK = createSDKInstance('service-account', resolvedDestToken);
    await destSDK.initializeClient();

    let vaultsToMigrate;
    if (selectedVaults && selectedVaults.length > 0) {
      vaultsToMigrate = selectedVaults.map(v => ({ id: v.vaultId, name: v.vaultName, suffix: v.suffix || '' }));
    } else {
      vaultsToMigrate = await sourceSDK.listVaults();
    }

    const totalVaults = vaultsToMigrate.length;
    let completedVaults = 0;
    const migrationResults = [];

    for (const vault of vaultsToMigrate) {
      if (isMigrationCancelled) {
        logger.info(null, 'Bulk migration cancelled by user');
        sseWrite(`data: ${JSON.stringify({ success: false, message: 'Migration cancelled by user', results: migrationResults })}\n\n`);
        clearInterval(keepAliveInterval);
        if (clientConnected) res.end();
        return;
      }

      sseWrite(`data: ${JSON.stringify({
        progress: (completedVaults / totalVaults) * 100,
        outcome: { vaultId: vault.id, vaultName: vault.name, phase: 'preparing', message: 'Preparing vault...' }
      })}\n\n`);

      try {
        const progressCallback = (itemsProcessed, totalItems, successCount, failureCount) => {
          const vaultProgress = itemsProcessed / totalItems;
          const overallProgress = ((completedVaults + vaultProgress) / totalVaults) * 100;
          sseWrite(`data: ${JSON.stringify({
            progress: overallProgress,
            outcome: {
              vaultId: vault.id, vaultName: vault.name, phase: 'migrating',
              message: `Migrating items (${itemsProcessed}/${totalItems})...`,
              itemsProcessed, totalItems, successCount, failureCount
            }
          })}\n\n`);
        };

        const result = await migrateVault(
          vault.id, vault.name, resolvedSourceToken, resolvedDestToken, sourceSDK, destSDK,
          () => isMigrationCancelled, progressCallback, mode, resolvedDestAccount, vault.suffix || ''
        );

        const { itemsLength, migrationResults: vaultResults, sourceItemCount, destItemCount, successCount, failureCount } = result;

        const outcome = {
          vaultId: vault.id, vaultName: vault.name,
          success: failureCount === 0 && sourceItemCount === destItemCount,
          message: failureCount === 0 && sourceItemCount === destItemCount
            ? `Successfully migrated vault "${vault.name}" with ${itemsLength} items`
            : `Vault "${vault.name}" completed with ${failureCount} failures out of ${itemsLength} items`,
          results: vaultResults, sourceItemCount, destItemCount, successCount, failureCount, phase: 'completed'
        };

        migrationResults.push(outcome);
        completedVaults++;
        sseWrite(`data: ${JSON.stringify({ progress: (completedVaults / totalVaults) * 100, outcome })}\n\n`);

      } catch (error) {
        logger.error(vault.id, `Vault migration failed: ${error.message}`);
        logger.logFailedVault(vault.id, vault.name, error);
        const outcome = {
          vaultId: vault.id, vaultName: vault.name, success: false,
          message: `Failed to migrate vault "${vault.name}": ${error.message}`,
          error: error.message, phase: 'failed'
        };
        migrationResults.push(outcome);
        completedVaults++;
        sseWrite(`data: ${JSON.stringify({ progress: (completedVaults / totalVaults) * 100, outcome })}\n\n`);
      }
    }

    const failedVaults = migrationResults.filter(r => !r.success);
    const summary = logger.getSummary();
    const rateLimit = { used: rateLimitTracker.getUsed(), remaining: rateLimitTracker.getRemaining() };

    if (failedVaults.length > 0) {
      sseWrite(`data: ${JSON.stringify({
        success: false,
        message: `Migration completed with ${failedVaults.length} vault failures out of ${vaultsToMigrate.length} vaults`,
        results: migrationResults, summary, rateLimit, finished: true
      })}\n\n`);
    } else {
      sseWrite(`data: ${JSON.stringify({
        success: true,
        message: `Successfully migrated all ${vaultsToMigrate.length} vaults`,
        results: migrationResults, summary, rateLimit, finished: true
      })}\n\n`);
    }

    clearInterval(keepAliveInterval);
    if (clientConnected) res.end();

  } catch (error) {
    logger.error(null, `Bulk migration failed: ${error.message}`);
    sseWrite(`data: ${JSON.stringify({ success: false, message: `Failed to migrate vaults: ${error.message}`, finished: true })}\n\n`);
    clearInterval(keepAliveInterval);
    if (clientConnected) res.end();
  }
});
app.get('/migration/download-log', (req, res) => {
  const logContent = logger.getGlobalLog();
  const summary = logger.getSummary();
  const vaultStatsSummary = logger.getVaultStatsSummary();
  const failureSummary = logger.getFailureSummary();
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');

  res.setHeader('Content-Type', 'text/plain');
  res.setHeader('Content-Disposition', `attachment; filename=migration-log-${timestamp}.txt`);
  res.send(`1Password Vault Migration Log
Generated: ${new Date().toISOString()}
Total Entries: ${summary.totalEntries}
Errors: ${summary.errors}
Warnings: ${summary.warnings}
Vaults Processed: ${summary.vaults}
Failed Vaults: ${summary.failedVaults}
Failed Items: ${summary.failedItems}

${'='.repeat(80)}

${vaultStatsSummary}
${failureSummary}

${'='.repeat(80)}
DETAILED LOG
${'='.repeat(80)}

${logContent}`);
});

app.get('/migration/download-vault-log/:vaultId', (req, res) => {
  const { vaultId } = req.params;
  const logContent = logger.getVaultLog(vaultId);

  if (!logContent) {
    return res.status(404).send('No log found for this vault');
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  res.setHeader('Content-Type', 'text/plain');
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
class OnePasswordSDK {
  constructor({ token, authMode = 'service-account', accountName } = {}) {
    this.token = token || null;
    this.authMode = authMode;
    this.accountName = accountName || null;
    this.client = null;
  }

  async initializeClient() {
    if (this.client) return;

    try {
      logger.info(null, `Initializing 1Password SDK client (mode: ${this.authMode})`);

      if (this.authMode === 'desktop') {
        if (!this.accountName) throw new Error('Account name is required for desktop auth.');
        this.client = await sdk.createClient({
          auth: new sdk.DesktopAuth(this.accountName),
          integrationName: "1Password Vault Migration Tool",
          integrationVersion: "2.1.0",
        });
      } else {
        if (!this.token) throw new Error('Service account token is required.');
        this.client = await sdk.createClient({
          auth: this.token,
          integrationName: "1Password Vault Migration Tool",
          integrationVersion: "2.1.0",
        });
      }
    } catch (error) {
      logger.error(null, `Failed to initialize client: ${error.message}`);
      throw new Error(`Failed to initialize client: ${error.message}`);
    }
  }

  async listVaults() {
    try {
      if (!this.client) await this.initializeClient();
      const vaults = await this.client.vaults.list();
      const CONCURRENCY = 10;
      const vaultList = [];

      for (let i = 0; i < vaults.length; i += CONCURRENCY) {
        const batch = vaults.slice(i, i + CONCURRENCY);
        const batchResults = await Promise.all(batch.map(async (vault) => {
          const vaultEntry = { id: vault.id, name: vault.title, vaultType: 'shared' };

          try {
            const overview = await this.client.vaults.getOverview(vault.id);
            vaultEntry.name = overview.title || vault.title;

            const vType = (overview.type || '').toLowerCase();
            const vName = (vaultEntry.name || '').toLowerCase();
            if (vType === 'private' || vType === 'employee' || vType === 'personal'
                || vName === 'private' || vName === 'employee') {
              vaultEntry.vaultType = 'personal';
            }
          } catch {
            const vName = (vaultEntry.name || '').toLowerCase();
            if (vName === 'private' || vName === 'employee') {
              vaultEntry.vaultType = 'personal';
            }
          }

          return vaultEntry;
        }));
        vaultList.push(...batchResults);
      }

      logger.info(null, `Listed ${vaultList.length} vaults (${vaultList.filter(v => v.vaultType === 'personal').length} personal, ${vaultList.filter(v => v.vaultType === 'shared').length} shared)`);
      return vaultList;
    } catch (error) {
      logger.error(null, `Failed to list vaults: ${error.message}`);
      throw new Error(`Failed to list vaults: ${error.message}`);
    }
  }

  async listVaultItems(vaultId) {
    try {
      if (!this.client) await this.initializeClient();
      logger.info(vaultId, `Listing items for vault`);

      const itemOverviews = await this.client.items.list(vaultId);
      const itemIds = itemOverviews.map(item => item.id);
      logger.info(vaultId, `Found ${itemIds.length} item IDs, batch fetching full details...`);

      if (itemIds.length === 0) return [];
      for (const overview of itemOverviews) {
        if (DEBUG_ENABLED) {
          logger.info(vaultId, `[DEBUG] Found item in overview list: "${overview.title}" [${overview.id}] category="${overview.category}"`);
        }
      }
      const BATCH_GET_SIZE = 50;
      const fullItems = [];

      for (let i = 0; i < itemIds.length; i += BATCH_GET_SIZE) {
        const chunkIds = itemIds.slice(i, i + BATCH_GET_SIZE);

        try {
          const batchResponse = await retryWithBackoff(() =>
            this.client.items.getAll(vaultId, chunkIds)
          );

          for (let idx = 0; idx < batchResponse.individualResponses.length; idx++) {
            const res = batchResponse.individualResponses[idx];
            if (res.content) {
              if (DEBUG_ENABLED) {
                logger.info(vaultId, `[DEBUG] getAll returned "${res.content.title}" [${res.content.id}] — category: "${res.content.category}", fields: ${res.content.fields?.length || 0}, sections: ${res.content.sections?.length || 0}`);
                logger.info(vaultId, `[DEBUG] getAll raw fields: ${JSON.stringify(redactFieldsForLog(res.content.fields || []))}`);
                logger.info(vaultId, `[DEBUG] getAll raw sections: ${JSON.stringify(res.content.sections || [])}`);
              }
              fullItems.push(res.content);
            } else if (res.error) {
              const errMsg = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
              const failedItemId = chunkIds[idx] || 'unknown';
              logger.error(vaultId, `Batch get failed for item [${failedItemId}]: ${errMsg}`);
              const matchingOverview = itemOverviews.find(o => o.id === failedItemId);
              if (matchingOverview && DEBUG_ENABLED) {
                logger.error(vaultId, `[DEBUG] getAll FAILED for item "${matchingOverview.title}" [${failedItemId}]: ${formatErrorForLog(typeof res.error === 'object' ? res.error : { message: errMsg })}`);
                logger.error(vaultId, `[DEBUG] Raw getAll error object: ${JSON.stringify(res.error)}`);
              }
            }
          }
        } catch (batchError) {
          logger.warning(vaultId, `Batch getAll failed, falling back to individual gets: ${batchError.message}`);
          for (const id of chunkIds) {
            try {
              const item = await retryWithBackoff(() => this.client.items.get(vaultId, id));
              if (DEBUG_ENABLED) {
                logger.info(vaultId, `[DEBUG] Individual get returned "${item.title}" [${item.id}] — category: "${item.category}", fields: ${item.fields?.length || 0}, sections: ${item.sections?.length || 0}`);
                logger.info(vaultId, `[DEBUG] Individual get raw fields: ${JSON.stringify(redactFieldsForLog(item.fields || []))}`);
              }

              fullItems.push(item);
            } catch (itemError) {
              logger.error(vaultId, `Failed to get item ${id}: ${formatErrorForLog(itemError)}`);
              const matchingOverview = itemOverviews.find(o => o.id === id);
              if (matchingOverview && DEBUG_ENABLED) {
                logger.error(vaultId, `[DEBUG] Individual get FAILED for "${matchingOverview.title}" [${id}]: ${formatErrorForLog(itemError)}`);
              }
            }
          }
        }
      }

      logger.info(vaultId, `Fetched ${fullItems.length} full items, processing fields and files...`);
      const items = [];
      for (const fullItem of fullItems) {
        try {
          const websites = fullItem.urls || fullItem.websites || fullItem.websiteUrls || [];
          const itemData = {
            id: fullItem.id,
            title: fullItem.title,
            category: fullItem.category,
            vaultId: fullItem.vaultId,
            fields: fullItem.fields || [],
            sections: fullItem.sections || [],
            tags: fullItem.tags || [],
            websites,
            notes: fullItem.notes || ""
          };
          if (itemData.fields) {
            itemData.fields = itemData.fields.map(field => {
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
            });
          }
          if (DEBUG_ENABLED) {
            logger.info(vaultId, `[DEBUG] Processed "${itemData.title}" [${itemData.id}] — category: "${itemData.category}", fields after normalization: ${JSON.stringify(redactFieldsForLog(itemData.fields || []))}`);
          }
          if (fullItem.files && fullItem.files.length > 0) {
            const filePromises = fullItem.files.map(file =>
              retryWithBackoff(() => this.client.items.files.read(vaultId, fullItem.id, file.attributes))
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
            itemData.files = (await Promise.all(filePromises)).filter(f => f !== null);
          }
          if (fullItem.category === sdk.ItemCategory.Document && fullItem.document) {
            try {
              const documentContent = await retryWithBackoff(() =>
                this.client.items.files.read(vaultId, fullItem.id, fullItem.document)
              );
              itemData.document = { name: fullItem.document.name, content: documentContent };
            } catch (docError) {
              logger.warning(vaultId, `Failed to read document for ${fullItem.title}: ${docError.message}`);
            }
          }

          items.push(itemData);
        } catch (processError) {
          logger.error(vaultId, `Failed to process item ${fullItem.id}: ${processError.message}`);
          if (DEBUG_ENABLED) {
            logger.error(vaultId, `[DEBUG] Processing FAILED for item "${fullItem.title}" [${fullItem.id}]: ${formatErrorForLog(processError)}`);
          }
        }
      }

      logger.info(vaultId, `Listed ${items.length} items successfully`);
      return items;

    } catch (error) {
      logger.error(vaultId, `Failed to list items: ${error.message}`);
      throw new Error(`Failed to list items for vault ${vaultId}: ${error.message}`);
    }
  }
}
const PORT = 3001;
const attrs = [{ name: 'commonName', value: 'localhost' }];
const opts = { keySize: 2048, algorithm: 'sha256', days: 365 };

try {
  const pems = await selfsigned.generate(attrs, opts);
  const options = { key: pems.private, cert: pems.cert };

  https.createServer(options, app).listen(PORT, () => {
    console.log(`
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   1Password Vault Migration Tool v2.1                        ║
║   Server started successfully on port ${PORT}                    ║
║   Access at: https://localhost:${PORT}                          ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
    `);
    logger.info(null, `Server started on port ${PORT}`);
  });
} catch (error) {
  console.error('Fatal error starting server:', error);
  logger.error(null, `Fatal error starting server: ${error.message}`);
  process.exit(1);
}
