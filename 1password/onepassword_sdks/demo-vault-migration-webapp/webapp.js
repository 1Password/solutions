// Load required modules and initialize express - ES Module syntax
import sdk from '@1password/sdk';
import { execSync } from 'child_process';
import express from 'express';
import bodyParser from 'body-parser';
import path from 'path';
import { fileURLToPath } from 'url';
import https from 'https';
import selfsigned from 'selfsigned';

const app = express();

// Get __dirname equivalent in ES modules
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// In-memory log storage with timestamps and severity levels
class LogManager {
  constructor() {
    this.globalLog = [];
    this.vaultLogs = {};
    this.errorCount = 0;
    this.warningCount = 0;
    this.failedItems = [];
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
      failedItems: this.failedItems.length
    };
  }

  getFailureSummary() {
    if (this.failedItems.length === 0) {
      return '\n═══════════════════════════════════════════════════════════════════════════════\n' +
             '✓ NO FAILED ITEMS - All items migrated successfully!\n' +
             '═══════════════════════════════════════════════════════════════════════════════\n';
    }

    let summary = '\n';
    summary += '═══════════════════════════════════════════════════════════════════════════════\n';
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
    this.vaultSummaries = {};
  }
}

const logger = new LogManager();

// Set up views and middleware
app.set('views', path.join(__dirname, 'views'));
app.set('view engine', 'ejs');
app.use(express.static('public'));
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());

// Global error handlers
process.on('uncaughtException', (error) => {
  logger.error(null, `Uncaught Exception: ${error.message}`);
  console.error('Uncaught Exception:', error);
});

process.on('unhandledRejection', (reason, promise) => {
  logger.error(null, `Unhandled Rejection: ${reason}`);
  console.error('Unhandled Rejection at:', promise, 'reason:', reason);
});

// --- Utility functions ---

// Retry function for handling conflicts or rate limits
const retryWithBackoff = async (fn, maxRetries = 3, baseDelay = 1000) => {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      if (
        (error.message.includes('data conflict') || error.message.includes('rate limit')) &&
        attempt < maxRetries
      ) {
        const delay = baseDelay * Math.pow(2, attempt - 1);
        logger.warning(null, `Retrying attempt ${attempt} after ${delay}ms due to ${error.message}`);
        await new Promise(resolve => setTimeout(resolve, delay));
      } else {
        throw error;
      }
    }
  }
};

// Check if a category string represents a CUSTOM item
function isCustomCategory(category) {
  const catStr = String(category).toLowerCase();
  return catStr === 'custom' || catStr === 'unsupported';
}

// Map a field type to its SDK equivalent, with a fallback to Text
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

// Build a standard field object for migration
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

  // Handle Address fields
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
  // Handle SSH Key fields
  else if (field.fieldType === sdk.ItemFieldType.SshKey && field.details?.content) {
    newField.value = field.details.content.privateKey || field.value || "";
  }
  // Handle TOTP fields
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
  // Handle Reference fields - keep the source item ID as value for now;
  // it will be remapped to the destination item ID after batch creation
  else if (field.fieldType === sdk.ItemFieldType.Reference) {
    newField.fieldType = sdk.ItemFieldType.Reference;
    newField.value = field.value || "";
    // Tag it so we can find it later for remapping
    newField._isReference = true;
    newField._sourceRefId = field.value || "";
  }

  return newField;
}

// Build credit card fields with special type mappings
// Key insight from working Python Lambda: built-in CC fields MUST have section_id=""
// and a section with id="" must exist as the FIRST section. Fields should be ordered:
// built-in fields first, then sectioned fields.
function buildCreditCardFields(fields, vaultId = null) {
  // Built-in credit card field IDs — these render at the top of the card
  // and MUST have sectionId: "" (empty string, not null/undefined)
  const builtInFieldIds = new Set([
    "cardholder", "type", "number", "ccnum", "cvv", "expiry", "validFrom"
  ]);

  // All known standard CC field IDs (built-in + sectioned) — these should
  // never be reassigned to "add more"
  const knownFieldIds = new Set([
    "cardholder", "type", "number", "ccnum", "cvv", "expiry", "validFrom",
    "bank", "phoneLocal", "phoneTollFree", "phoneIntl", "website",
    "pin", "creditLimit", "cashLimit", "interest", "issuenumber"
  ]);

  const builtInFields = [];   // Fields that go in the root "" section (top of card)
  const sectionFields = [];   // Fields that go in named sections

  for (const field of fields) {
    const fieldId = field.id || "unnamed";
    const newField = {
      id: fieldId,
      title: field.title || field.label || "unnamed",
      fieldType: field.fieldType || sdk.ItemFieldType.Text,
      value: field.value || "",
    };

    const titleLower = (field.title || '').toLowerCase();

    // Handle "Unsupported" fieldType from the SDK
    if (field.fieldType === 'Unsupported' || field.fieldType === sdk.ItemFieldType.Unsupported) {
      if (fieldId === 'expiry' || fieldId === 'validFrom') {
        newField.fieldType = sdk.ItemFieldType.MonthYear;
      } else {
        newField.fieldType = sdk.ItemFieldType.Text;
      }
    }

    // Card type mapping
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

    // Expiry / validFrom date normalization
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

    // Credit card number — match ONLY the actual card number fields
    if (fieldId === "number" || fieldId === "ccnum") {
      newField.fieldType = sdk.ItemFieldType.CreditCardNumber;
    }

    if (fieldId === "cvv" || titleLower.includes("verification")) {
      newField.fieldType = sdk.ItemFieldType.Concealed;
    }

    if (fieldId === "pin" || titleLower === "pin") {
      newField.fieldType = sdk.ItemFieldType.Concealed;
    }

    // Route to built-in or sectioned bucket
    if (builtInFieldIds.has(fieldId)) {
      // Built-in fields ALWAYS get sectionId: "" — this is critical for rendering
      newField.sectionId = "";
      builtInFields.push(newField);
    } else {
      // Sectioned fields keep their original sectionId from the source
      const sourceSectionId = field.sectionId;
      if (sourceSectionId && sourceSectionId !== "" && sourceSectionId !== null) {
        newField.sectionId = sourceSectionId;
      } else if (knownFieldIds.has(fieldId)) {
        // Known field with no section — assign to "" (root)
        newField.sectionId = "";
      } else {
        // Truly custom/unknown field with no section
        newField.sectionId = "add more";
      }
      sectionFields.push(newField);
    }
  }

  // Built-in fields first (renders at top of card), then sectioned fields
  const result = [...builtInFields, ...sectionFields];

  return result;
}

// Convert a CUSTOM item to a Login item, preserving concealed fields and structure.
// Login items in 1Password have a specific layout:
//   - username, password, OTP are "built-in" root fields (NO sectionId) → render at top
//   - all other fields live inside named sections
// We detect built-in fields by label/id/type and strip their sectionId so they
// render correctly, then keep everything else in its original section.
function buildCustomAsLogin(item, vaultId) {
  logger.info(vaultId, `Converting CUSTOM item "${item.title}" to Login category (preserving concealed fields)`);

  const newItem = {
    title: item.title,
    category: sdk.ItemCategory.Login,
    vaultId: null, // will be set by caller
  };

  if (item.notes && item.notes.trim() !== "") {
    newItem.notes = item.notes;
  }

  if (item.fields && item.fields.length > 0) {
    // First pass: classify each field
    const builtInFields = [];  // username, password, OTP → go to root (no sectionId)
    const sectionFields = [];  // everything else → keep in sections

    for (const field of item.fields) {
      const label = (field.title || field.label || '').toLowerCase();
      const fieldType = field.fieldType;
      const fieldId = (field.id || '').toLowerCase();

      // Detect username
      if (fieldId === 'username' || label === 'username' || label === 'user' ||
          label === 'email address' || label === 'login') {
        builtInFields.push({
          id: "username",
          title: field.title || field.label || "username",
          fieldType: sdk.ItemFieldType.Text,
          value: field.value || "",
          // NO sectionId — root-level built-in
        });
        continue;
      }

      // Detect password
      if (fieldId === 'password' || label === 'password' || label === 'pass' ||
          (fieldType === sdk.ItemFieldType.Concealed && label.includes('password'))) {
        builtInFields.push({
          id: "password",
          title: field.title || field.label || "password",
          fieldType: sdk.ItemFieldType.Concealed,
          value: field.value || "",
          // NO sectionId — root-level built-in
        });
        continue;
      }

      // Detect OTP/TOTP
      if (fieldType === sdk.ItemFieldType.Totp || label === 'otp' ||
          label === 'one-time password' || label === 'totp' ||
          fieldId === 'totp' || fieldId === 'otp') {
        const totpValue = field.value || field.details?.content?.totp || "";
        builtInFields.push({
          id: "onetimepassword",
          title: field.title || field.label || "one-time password",
          fieldType: sdk.ItemFieldType.Totp,
          value: totpValue,
          // NO sectionId — root-level built-in
        });
        continue;
      }

      // Everything else: preserve in its section with correct type
      const mapped = buildMigratedField(field);
      // Ensure concealed fields stay concealed
      if (fieldType === sdk.ItemFieldType.Concealed) {
        mapped.fieldType = sdk.ItemFieldType.Concealed;
      }
      // If the field had no section, put it in a default section so it doesn't
      // collide with the built-in root area
      if (mapped.sectionId === undefined) {
        mapped.sectionId = "additional";
      }
      sectionFields.push(mapped);
    }

    // Built-in fields first (username, password, OTP), then section fields in original order
    newItem.fields = [...builtInFields, ...sectionFields];
  }

  // Preserve sections in original order
  if (item.sections && item.sections.length > 0) {
    newItem.sections = item.sections.map(section => ({
      id: section.id,
      title: section.title || section.label || ""
    }));
  }

  // Ensure the "additional" fallback section exists if we used it
  if (newItem.fields?.some(f => f.sectionId === "additional")) {
    if (!newItem.sections) newItem.sections = [];
    if (!newItem.sections.some(s => s.id === "additional")) {
      newItem.sections.push({ id: "additional", title: "Additional Details" });
    }
  }

  // Preserve files
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

  // Preserve tags
  if (item.tags && item.tags.length > 0) {
    newItem.tags = item.tags;
  }

  // Preserve websites
  if (item.websites && item.websites.length > 0) {
    newItem.websites = item.websites.map(website => ({
      url: website.url || website.href || "",
      label: website.label || "website",
      autofillBehavior: website.autofillBehavior || sdk.AutofillBehavior.AnywhereOnWebsite
    }));
  }

  return newItem;
}

// Build a new item object for SDK creation from a source item
function buildNewItem(item, newVaultId, vaultId) {
  // Handle CUSTOM items -> convert to Login
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

  // Notes
  if (item.notes && item.notes.trim() !== "") {
    newItem.notes = item.notes;
  } else if (item.category === sdk.ItemCategory.SecureNote) {
    newItem.notes = "Migrated Secure Note";
  }

  // SSH key category normalization
  if (item.category === 'SSH_KEY') {
    newItem.category = sdk.ItemCategory.SshKey;
  }

  // Credit card fields
  if (item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard) {
    newItem.category = sdk.ItemCategory.CreditCard;
    if (item.fields && item.fields.length > 0) {
      newItem.fields = buildCreditCardFields(item.fields, vaultId);
    }

    // For credit cards, the section with id="" MUST be FIRST — this is where
    // built-in fields (cardholder, type, number, cvv, expiry, validFrom) render.
    // Then named sections (contactInfo, details) follow in order.
    // This matches the Python Lambda pattern: ItemSection(id='', title='') first.
    newItem.sections = [
      { id: "", title: "" }  // Root section for built-in fields — MUST be first
    ];

    // Add named sections from source (skip the empty-string one since we added it)
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

    // Ensure every sectionId referenced by a field has a matching section
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
  // Standard fields (non-credit-card)
  else if (item.fields && item.fields.length > 0) {
    newItem.fields = item.fields.map(buildMigratedField);
  }
  // Secure notes without fields
  else if (item.category === sdk.ItemCategory.SecureNote) {
    newItem.notes = item.notes || "Migrated Secure Note";
  }

  // Sections (skip for credit cards — already handled above)
  if (!(item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard)) {
    if (item.sections && item.sections.length > 0) {
      newItem.sections = item.sections.map(section => ({
        id: section.id,
        title: section.title || section.label || ""
      }));
    }
  }

  // Files
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

  // Tags
  if (item.tags && item.tags.length > 0) {
    newItem.tags = item.tags;
  }

  // Websites
  if (item.websites && item.websites.length > 0) {
    newItem.websites = item.websites.map(website => ({
      url: website.url || website.href || "",
      label: website.label || "website",
      autofillBehavior: website.autofillBehavior || sdk.AutofillBehavior.AnywhereOnWebsite
    }));
  }

  return newItem;
}

// --- Routes ---

app.get('/', (req, res) => {
  res.render('welcome', { currentPage: 'welcome' });
});

app.get('/migration', (req, res) => {
  res.render('migration', { error: null, currentPage: 'migration' });
});

// List vaults using a service token
app.post('/migration/list-vaults', async (req, res) => {
  const { serviceToken } = req.body;
  if (!serviceToken) {
    return res.status(400).json({ success: false, error: 'Service token is required' });
  }

  try {
    logger.info(null, 'Listing vaults for source tenant');
    const sdkInstance = new OnePasswordSDK(serviceToken);
    await sdkInstance.initializeClient();
    const vaults = await sdkInstance.listVaults();

    const vaultsWithCounts = await Promise.all(vaults.map(async (vault) => {
      try {
        const count = await getVaultItemCount(vault.id, serviceToken, vault.name);
        logger.info(vault.id, `Vault ${vault.name}: ${count} items`);
        return { ...vault, itemCount: count };
      } catch (error) {
        logger.error(vault.id, `Failed to get item count: ${error.message}`);
        return { ...vault, itemCount: 0 };
      }
    }));

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

// Get item count for a vault
async function getVaultItemCount(vaultId, token, vaultName = 'Unknown') {
  try {
    const sdkInstance = new OnePasswordSDK(token);
    await sdkInstance.initializeClient();
    const activeItems = await sdkInstance.client.items.list(vaultId);
    const activeCount = activeItems.length;

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

    return activeCount;
  } catch (error) {
    logger.error(vaultId, `Error fetching item count: ${error.message}`);
    return 0;
  }
}

// --- Unified vault migration function (handles optional progress callback) ---
// Strategy:
//   1. Build all new items, stripping Reference fields entirely (SDK rejects empty refs)
//   2. Separate items with binary content (documents/files) — these must be created individually
//   3. Batch create the rest using createAll
//   4. Build sourceId → destId map from responses
//   5. For items that had Reference fields, fetch the dest item, add the ref field
//      with the remapped dest ID, and save via items.put

const BATCH_SIZE = 50; // createAll batch size limit

async function migrateVault(vaultId, vaultName, sourceToken, destToken, sourceSDK, destSDK, isCancelled, onProgress = null) {
  logger.info(vaultId, `Starting migration for vault ${vaultName}`);

  // Get source item count
  const sourceItemCount = await getVaultItemCount(vaultId, sourceToken, vaultName);
  logger.info(vaultId, `Source item count: ${sourceItemCount}`);

  // Create destination vault using CLI
  let newVaultId;
  try {
    const destEnv = { ...process.env, OP_SERVICE_ACCOUNT_TOKEN: destToken };
    const createVaultCommand = `op vault create "${vaultName}" --format json`;
    const newVaultOutput = execSync(createVaultCommand, { env: destEnv, encoding: 'utf8' });
    const newVault = JSON.parse(newVaultOutput);
    newVaultId = newVault.id;
    logger.info(vaultId, `Created destination vault ${newVaultId}`);
  } catch (error) {
    logger.error(vaultId, `Failed to create destination vault: ${error.message}`);
    throw new Error(`Vault creation failed: ${error.message}`);
  }

  // Get items to migrate
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

  // sourceId → destId map for reference remapping
  const idMap = new Map();
  // Track which built items have reference fields that need remapping
  // Each entry: { sourceItemId, destItemId (filled after create), refFields: [{fieldId, sourceRefId}] }
  const itemsWithRefs = [];

  // --- Phase 1: Build all new item objects ---
  logger.info(vaultId, `Phase 1: Building item objects...`);

  const batchableItems = [];    // items that can go through createAll (no binary)
  const individualItems = [];   // items with documents/files/credit cards that need individual create

  for (const item of items) {
    try {
      const categoryStr = String(item.category);
      logger.info(vaultId, `Item "${item.title}" category: ${categoryStr}`);

      // Fetch document content for Document items
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

      // For credit cards, fetch full item to get all fields
      if (item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard) {
        try {
          const fullItem = await retryWithBackoff(() => sourceSDK.client.items.get(vaultId, item.id));
          item.fields = fullItem.fields;

          // The SDK returns fieldType "Unsupported" and empty value for the expiry
          // field. Fall back to CLI to retrieve the actual expiry date.
          const expiryField = item.fields?.find(f => f.id === 'expiry');
          if (expiryField && (!expiryField.value || expiryField.fieldType === 'Unsupported')) {
            try {
              const sourceEnv = { ...process.env, OP_SERVICE_ACCOUNT_TOKEN: sourceToken };
              const cliOutput = execSync(
                `op item get "${item.id}" --vault "${vaultId}" --format json`,
                { env: sourceEnv, encoding: 'utf8' }
              );
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

      // Build the new item
      const newItem = buildNewItem(item, newVaultId, vaultId);

      // Attach document if present
      if (item.document) {
        newItem.document = item.document;
      }

      // Check for reference fields — REMOVE them entirely for initial creation
      // (SDK rejects Reference fields with empty/invalid values)
      // We'll add them back in Phase 3 after we have the sourceId→destId map
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
            // Don't include this field in the item — skip it
          } else {
            // Clean up internal tags before sending to SDK
            delete field._isReference;
            delete field._sourceRefId;
            fieldsWithoutRefs.push(field);
          }
        }
        newItem.fields = fieldsWithoutRefs;
      }

      // Determine if this item needs individual creation:
      // - Items with binary content (files/documents)
      // - Credit card items (batch createAll has issues with CreditCard category)
      const isCreditCard = item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard;
      const hasBinary = !!(item.document || (item.files && item.files.length > 0));
      const needsIndividualCreate = hasBinary || isCreditCard;

      const entry = { sourceId: item.id, sourceTitle: item.title, newItem, refFields, hasBinary: needsIndividualCreate };

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

  // --- Phase 2: Create items ---
  logger.info(vaultId, `Phase 2: Creating items (${batchableItems.length} batchable, ${individualItems.length} individual)...`);

  // 2a: Batch create items in chunks using createAll
  for (let i = 0; i < batchableItems.length; i += BATCH_SIZE) {
    if (isCancelled()) {
      logger.info(vaultId, `Migration cancelled by user`);
      return { itemsLength: items.length, migrationResults, sourceItemCount, destItemCount: null, successCount, failureCount };
    }

    const chunk = batchableItems.slice(i, i + BATCH_SIZE);
    const itemsForBatch = chunk.map(entry => entry.newItem);

    try {
      const batchResponse = await retryWithBackoff(() =>
        destSDK.client.items.createAll(newVaultId, itemsForBatch)
      );

      for (let j = 0; j < batchResponse.individualResponses.length; j++) {
        const res = batchResponse.individualResponses[j];
        const entry = chunk[j];
        processedItems++;

        if (res.content) {
          // Map source ID → destination ID
          idMap.set(entry.sourceId, res.content.id);
          successCount++;
          migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: true, progress: (processedItems / items.length) * 100 });
          logger.info(vaultId, `Batch created item [${entry.sourceId}] "${entry.sourceTitle}" → ${res.content.id}`, { itemId: entry.sourceId });

          // Track if it has reference fields to remap
          if (entry.refFields.length > 0) {
            itemsWithRefs.push({ sourceItemId: entry.sourceId, destItemId: res.content.id, refFields: entry.refFields });
          }
        } else if (res.error) {
          failureCount++;
          const errMsg = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
          logger.logFailedItem(vaultId, vaultName, entry.sourceId, entry.sourceTitle, new Error(errMsg));
          migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: false, error: errMsg, progress: (processedItems / items.length) * 100 });
        }
      }
    } catch (error) {
      // If the entire batch fails, log each item as failed
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

  // 2b: Create items with binary content or credit cards individually
  for (const entry of individualItems) {
    if (isCancelled()) {
      logger.info(vaultId, `Migration cancelled by user`);
      return { itemsLength: items.length, migrationResults, sourceItemCount, destItemCount: null, successCount, failureCount };
    }

    try {
      const createdItem = await retryWithBackoff(() => destSDK.client.items.create(entry.newItem));

      idMap.set(entry.sourceId, createdItem.id);
      processedItems++;
      successCount++;
      migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: true, progress: (processedItems / items.length) * 100 });
      logger.info(vaultId, `Created item [${entry.sourceId}] "${entry.sourceTitle}" → ${createdItem.id} (individual)`, { itemId: entry.sourceId });

      if (entry.refFields.length > 0) {
        itemsWithRefs.push({ sourceItemId: entry.sourceId, destItemId: createdItem.id, refFields: entry.refFields });
      }
    } catch (error) {
      processedItems++;
      failureCount++;
      logger.logFailedItem(vaultId, vaultName, entry.sourceId, entry.sourceTitle, error);
      migrationResults.push({ id: entry.sourceId, title: entry.sourceTitle, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
    }

    if (onProgress && (processedItems % 3 === 0 || processedItems === items.length)) {
      onProgress(processedItems, items.length, successCount, failureCount);
    }
  }

  // --- Phase 3: Add reference fields with remapped IDs ---
  if (itemsWithRefs.length > 0) {
    logger.info(vaultId, `Phase 3: Adding reference fields to ${itemsWithRefs.length} items...`);

    for (const ref of itemsWithRefs) {
      try {
        // Fetch the created item from destination
        const destItem = await retryWithBackoff(() => destSDK.client.items.get(newVaultId, ref.destItemId));

        let updated = false;
        for (const refField of ref.refFields) {
          const newRefId = idMap.get(refField.sourceRefId);
          if (newRefId) {
            // Add the reference field to the destination item
            if (!destItem.fields) destItem.fields = [];
            destItem.fields.push({
              id: refField.fieldId,
              title: refField.title || "Reference",
              fieldType: sdk.ItemFieldType.Reference,
              value: newRefId,
              ...(refField.sectionId ? { sectionId: refField.sectionId } : {})
            });

            // Ensure the section exists if the field references one
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
          logger.info(vaultId, `Updated item ${ref.destItemId} with reference fields`);
        }
      } catch (error) {
        logger.warning(vaultId, `Failed to add references for item ${ref.destItemId}: ${error.message}`);
      }
    }
  } else {
    logger.info(vaultId, `Phase 3: No reference fields to remap`);
  }

  // Get destination item count
  const destItemCount = await getVaultItemCount(newVaultId, destToken, vaultName);
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

// Migrate a single vault endpoint
app.post('/migration/migrate-vault', async (req, res) => {
  const { vaultId, vaultName, sourceToken, destToken } = req.body;

  if (!vaultId || !vaultName || !sourceToken || !destToken) {
    return res.status(400).json({ success: false, message: 'Vault ID, vault name, source token, and destination token are required' });
  }

  try {
    const sourceSDK = new OnePasswordSDK(sourceToken);
    await sourceSDK.initializeClient();
    const destSDK = new OnePasswordSDK(destToken);
    await destSDK.initializeClient();

    const result = await migrateVault(vaultId, vaultName, sourceToken, destToken, sourceSDK, destSDK, () => isMigrationCancelled);
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

// Migrate multiple vaults with Server-Sent Events
app.get('/migration/migrate-all-vaults', async (req, res) => {
  const { sourceToken, destToken, vaults } = req.query;
  let selectedVaults;

  try {
    selectedVaults = vaults ? JSON.parse(decodeURIComponent(vaults)) : null;
  } catch (error) {
    selectedVaults = null;
  }

  if (!sourceToken || !destToken) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.flushHeaders();
    res.write(`data: ${JSON.stringify({ success: false, message: 'Source token and destination token are required', finished: true })}\n\n`);
    res.end();
    return;
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.flushHeaders();

  const keepAliveInterval = setInterval(() => { res.write(': keep-alive\n\n'); }, 15000);
  isMigrationCancelled = false;
  logger.info(null, 'Starting bulk vault migration');

  try {
    const sourceSDK = new OnePasswordSDK(sourceToken);
    await sourceSDK.initializeClient();
    const destSDK = new OnePasswordSDK(destToken);
    await destSDK.initializeClient();

    let vaultsToMigrate;
    if (selectedVaults && selectedVaults.length > 0) {
      vaultsToMigrate = selectedVaults.map(v => ({ id: v.vaultId, name: v.vaultName }));
    } else {
      vaultsToMigrate = await sourceSDK.listVaults();
    }

    const totalVaults = vaultsToMigrate.length;
    let completedVaults = 0;
    const migrationResults = [];

    for (const vault of vaultsToMigrate) {
      if (isMigrationCancelled) {
        logger.info(null, 'Bulk migration cancelled by user');
        res.write(`data: ${JSON.stringify({ success: false, message: 'Migration cancelled by user', results: migrationResults })}\n\n`);
        clearInterval(keepAliveInterval);
        res.end();
        return;
      }

      const newVaultName = `${vault.name} (Migrated)`;

      res.write(`data: ${JSON.stringify({
        progress: (completedVaults / totalVaults) * 100,
        outcome: { vaultId: vault.id, vaultName: vault.name, phase: 'preparing', message: 'Preparing vault...' }
      })}\n\n`);

      try {
        const progressCallback = (itemsProcessed, totalItems, successCount, failureCount) => {
          const vaultProgress = itemsProcessed / totalItems;
          const overallProgress = ((completedVaults + vaultProgress) / totalVaults) * 100;
          res.write(`data: ${JSON.stringify({
            progress: overallProgress,
            outcome: {
              vaultId: vault.id, vaultName: vault.name, phase: 'migrating',
              message: `Migrating items (${itemsProcessed}/${totalItems})...`,
              itemsProcessed, totalItems, successCount, failureCount
            }
          })}\n\n`);
        };

        const result = await migrateVault(
          vault.id, newVaultName, sourceToken, destToken, sourceSDK, destSDK,
          () => isMigrationCancelled, progressCallback
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
        res.write(`data: ${JSON.stringify({ progress: (completedVaults / totalVaults) * 100, outcome })}\n\n`);

      } catch (error) {
        logger.error(vault.id, `Vault migration failed: ${error.message}`);
        const outcome = {
          vaultId: vault.id, vaultName: vault.name, success: false,
          message: `Failed to migrate vault "${vault.name}": ${error.message}`,
          error: error.message, phase: 'failed'
        };
        migrationResults.push(outcome);
        completedVaults++;
        res.write(`data: ${JSON.stringify({ progress: (completedVaults / totalVaults) * 100, outcome })}\n\n`);
      }
    }

    const failedVaults = migrationResults.filter(r => !r.success);
    const summary = logger.getSummary();

    if (failedVaults.length > 0) {
      res.write(`data: ${JSON.stringify({
        success: false,
        message: `Migration completed with ${failedVaults.length} vault failures out of ${vaultsToMigrate.length} vaults`,
        results: migrationResults, summary, finished: true
      })}\n\n`);
    } else {
      res.write(`data: ${JSON.stringify({
        success: true,
        message: `Successfully migrated all ${vaultsToMigrate.length} vaults`,
        results: migrationResults, summary, finished: true
      })}\n\n`);
    }

    clearInterval(keepAliveInterval);
    res.end();

  } catch (error) {
    logger.error(null, `Bulk migration failed: ${error.message}`);
    res.write(`data: ${JSON.stringify({ success: false, message: `Failed to migrate vaults: ${error.message}`, finished: true })}\n\n`);
    clearInterval(keepAliveInterval);
    res.end();
  }
});

// Log download endpoints
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

// --- 1Password SDK wrapper ---
class OnePasswordSDK {
  constructor(token) {
    this.token = token;
    this.client = null;
  }

  async initializeClient() {
    if (!this.token) throw new Error('Service account token is required.');
    if (this.client) return; // Reuse existing client

    try {
      logger.info(null, 'Initializing 1Password SDK client');
      this.client = await sdk.createClient({
        auth: this.token,
        integrationName: "1Password Vault Migration Tool",
        integrationVersion: "2.1.0",
      });
    } catch (error) {
      logger.error(null, `Failed to initialize client: ${error.message}`);
      throw new Error(`Failed to initialize client: ${error.message}`);
    }
  }

  async listVaults() {
    try {
      if (!this.client) await this.initializeClient();
      const vaults = await this.client.vaults.list();
      const vaultList = [];

      for (const vault of vaults) {
        // Use the new beta SDK getOverview for richer vault info
        try {
          const overview = await this.client.vaults.getOverview(vault.id);
          vaultList.push({ id: overview.id, name: overview.title || vault.title });
        } catch {
          vaultList.push({ id: vault.id, name: vault.title });
        }
      }

      logger.info(null, `Listed ${vaultList.length} vaults`);
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

      // Batch fetch full item details using getAll in chunks
      const BATCH_GET_SIZE = 50;
      const fullItems = [];

      for (let i = 0; i < itemIds.length; i += BATCH_GET_SIZE) {
        const chunkIds = itemIds.slice(i, i + BATCH_GET_SIZE);

        try {
          const batchResponse = await retryWithBackoff(() =>
            this.client.items.getAll(vaultId, chunkIds)
          );

          for (const res of batchResponse.individualResponses) {
            if (res.content) {
              fullItems.push(res.content);
            } else if (res.error) {
              const errMsg = typeof res.error === 'string' ? res.error : JSON.stringify(res.error);
              logger.error(vaultId, `Batch get failed for an item: ${errMsg}`);
            }
          }
        } catch (batchError) {
          // Fallback: if batch fails entirely, try items individually
          logger.warning(vaultId, `Batch getAll failed, falling back to individual gets: ${batchError.message}`);
          for (const id of chunkIds) {
            try {
              const item = await retryWithBackoff(() => this.client.items.get(vaultId, id));
              fullItems.push(item);
            } catch (itemError) {
              logger.error(vaultId, `Failed to get item ${id}: ${itemError.message}`);
            }
          }
        }
      }

      logger.info(vaultId, `Fetched ${fullItems.length} full items, processing fields and files...`);

      // Process each full item into our internal format
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

          // Normalize special field types
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

          // Read attached files (must be done individually — binary content)
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

          // Read document content
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

// --- Start HTTPS server ---
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