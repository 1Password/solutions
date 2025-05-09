const sdk = require('@1password/sdk');
const { execSync } = require('child_process');
const express = require('express');
const bodyParser = require('body-parser');
const session = require('express-session');
const path = require('path');
const https = require('https');
const selfsigned = require('selfsigned');
const app = express();

// In-memory log storage
let migrationLog = [];
let vaultLogs = {};

// Dynamically import p-limit for concurrency control
let pLimit;
async function loadPLimit() {
  try {
    const pLimitModule = await import('p-limit');
    pLimit = pLimitModule.default || pLimitModule;
  } catch (error) {
    console.error(`Failed to load p-limit: ${error.message}`);
    migrationLog.push(`[ERROR] Failed to load p-limit: ${error.message}`);
    // Fallback to no concurrency limit if p-limit fails
    pLimit = (limit) => (fn) => fn();
  }
}

// Start the app once p-limit is loaded
loadPLimit().then(() => {
  const VAULT_CONCURRENCY_LIMIT = 2;
  const ITEM_CONCURRENCY_LIMIT = 1;

  app.set('views', path.join(__dirname, 'views'));
  app.set('view engine', 'ejs');

  app.use(express.static('public'));
  app.use(bodyParser.urlencoded({ extended: true }));
  app.use(bodyParser.json());

  // Set up session handling
  app.use(session({
    secret: 'your-secret-key',
    resave: false,
    saveUninitialized: false,
    cookie: { secure: false, httpOnly: true, path: '/', maxAge: 24 * 60 * 60 * 1000 }
  }));

  // Show the welcome page
  app.get('/', (req, res) => {
    res.render('welcome', { currentPage: 'welcome' });
  });

  // Show the migration page
  app.get('/migration', (req, res) => {
    res.render('migration', { error: null, currentPage: 'migration' });
  });

  // List vaults using a service token
  app.post('/migration/list-vaults', async (req, res) => {
    const { serviceToken } = req.body;
    if (!serviceToken) {
      console.error('Service token is required');
      migrationLog.push(`[ERROR] Service token is required`);
      return res.status(400).json({ success: false, error: 'Service token is required' });
    }
    try {
      console.log('Listing vaults for source tenant');
      migrationLog.push(`[INFO] Listing vaults for source tenant`);
      const sdkInstance = new OnePasswordSDK(serviceToken);
      await sdkInstance.initializeClient();
      const vaults = await sdkInstance.listVaults();
      // Get item counts for each vault using CLI
      const vaultsWithCounts = await Promise.all(vaults.map(async (vault) => {
        const count = await getVaultItemCount(vault.id, serviceToken);
        console.log(`Vault ${vault.id} (${vault.name}): ${count} items`);
        migrationLog.push(`[INFO] Vault ${vault.id} (${vault.name}): ${count} items`);
        return { ...vault, itemCount: count };
      }));
      res.json({ success: true, vaults: vaultsWithCounts });
    } catch (error) {
      console.error(`Failed to list vaults: ${error.message}`);
      migrationLog.push(`[ERROR] Failed to list vaults: ${error.message}`);
      res.status(500).json({ success: false, error: error.message });
    }
  });

  let isMigrationCancelled = false;

  // Cancel an ongoing migration
  app.post('/migration/cancel', (req, res) => {
    isMigrationCancelled = true;
    console.log('Migration cancellation requested');
    migrationLog.push(`[INFO] Migration cancellation requested`);
    res.json({ success: true, message: 'Migration cancellation requested' });
  });

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
          console.log(`Retrying attempt ${attempt} after ${delay}ms due to ${error.message}`);
          migrationLog.push(`[INFO] Retrying attempt ${attempt} after ${delay}ms due to ${error.message}`);
          await new Promise(resolve => setTimeout(resolve, delay));
        } else {
          throw error;
        }
      }
    }
  };

  async function getVaultItemCount(vaultId, token, vaultName = 'Unknown') {
  try {
    const sdkInstance = new OnePasswordSDK(token);
    await sdkInstance.initializeClient();
    // Count active items
    const activeItems = await sdkInstance.client.items.list(vaultId);
    const activeCount = activeItems.length;
    // Count archived items
    const archivedItems = await sdkInstance.client.items.list(vaultId, {
      type: "ByState",
      content: { active: false, archived: true }
    });
    const archivedCount = archivedItems.length;
    // Log archived items if any
    if (archivedCount > 0) {
      const logMessage = `[INFO] Vault ${vaultId} (${vaultName}): Contains ${archivedCount} archived items`;
      console.log(logMessage);
      migrationLog.push(logMessage);
      if (vaultLogs[vaultId]) {
        vaultLogs[vaultId].push(logMessage);
      } else {
        vaultLogs[vaultId] = [logMessage];
      }
    }
    return activeCount; // Return only active item count for UI and migration
  } catch (error) {
    console.error(`Error fetching item count for vault ${vaultId}: ${error.message}`);
    migrationLog.push(`[ERROR] Vault ${vaultId} (${vaultName}): Failed to fetch item count - ${error.message}`);
    if (vaultLogs[vaultId]) {
      vaultLogs[vaultId].push(`[ERROR] Failed to fetch item count: ${error.message}`);
    }
    return 0;
  }
}

  // Migrate a single vault and its items
  async function migrateVault(vaultId, vaultName, sourceToken, destToken, sourceSDK, destSDK, isCancelled) {
    const logEntry = { vaultId, vaultName, timestamp: new Date().toISOString(), errors: [], itemResults: [] };
    // Initialize vault-specific log
    vaultLogs[vaultId] = vaultLogs[vaultId] || [];
    console.log(`Starting migration for vault ${vaultId} (${vaultName})`);
    migrationLog.push(`[INFO] Starting migration for vault ${vaultId} (${vaultName})`);
    vaultLogs[vaultId].push(`[INFO] Starting migration for vault ${vaultId} (${vaultName})`);

    try {
      // Get source item count
      const sourceItemCount = await getVaultItemCount(vaultId, sourceToken);
      logEntry.sourceItemCount = sourceItemCount;
      console.log(`Vault ${vaultId} (${vaultName}) source item count: ${sourceItemCount}`);
      migrationLog.push(`[INFO] Vault ${vaultId} (${vaultName}) source item count: ${sourceItemCount}`);
      vaultLogs[vaultId].push(`[INFO] Source item count: ${sourceItemCount}`);

      const destEnv = { ...process.env, OP_SERVICE_ACCOUNT_TOKEN: destToken };
      const createVaultCommand = `op vault create "${vaultName}" --format json`;
      const newVaultOutput = execSync(createVaultCommand, { env: destEnv, encoding: 'utf8' });
      const newVault = JSON.parse(newVaultOutput);
      const newVaultId = newVault.id;
      logEntry.newVaultId = newVaultId;
      console.log(`Created new vault ${newVaultId} (${vaultName}) in destination`);
      migrationLog.push(`[INFO] Created new vault ${newVaultId} (${vaultName}) in destination`);
      vaultLogs[vaultId].push(`[INFO] Created new vault ${newVaultId} (${vaultName}) in destination`);

      const items = await sourceSDK.listVaultItems(vaultId);
      const migrationResults = [];
      let processedItems = 0;

      for (const item of items) {
        if (isCancelled()) {
          logEntry.status = 'cancelled';
          console.log(`Migration cancelled for vault ${vaultId} (${vaultName})`);
          migrationLog.push(`[INFO] Vault ${vaultId} (${vaultName}): Migration cancelled`);
          vaultLogs[vaultId].push(`[INFO] Migration cancelled`);
          migrationLog.push(JSON.stringify(logEntry, null, 2));
          vaultLogs[vaultId].push(JSON.stringify(logEntry, null, 2));
          return { itemsLength: items.length, migrationResults, sourceItemCount, destItemCount: null };
        }

        const newItem = {
          title: item.title,
          category: item.category || sdk.ItemCategory.Login,
          vaultId: newVaultId
        };

        try {
          if (item.category === 'Document') {
            const fullItem = await retryWithBackoff(() => sourceSDK.client.items.get(vaultId, item.id));
            if (fullItem.category !== sdk.ItemCategory.Document || !fullItem.document) {
              throw new Error(`Item ${item.id} is not a Document or has no document`);
            }
            const documentContent = await retryWithBackoff(() => sourceSDK.client.items.files.read(vaultId, item.id, fullItem.document));
            newItem.document = {
              name: fullItem.document.name,
              content: documentContent instanceof Uint8Array ? documentContent : new Uint8Array(documentContent)
            };
          }

          if (item.category === 'SSH_KEY') {
            newItem.category = sdk.ItemCategory.SshKey;
          }

          if (item.category === 'CreditCard' || item.category === sdk.ItemCategory.CreditCard) {
            newItem.category = sdk.ItemCategory.CreditCard;
            const fullItem = await retryWithBackoff(() => sourceSDK.client.items.get(vaultId, item.id));
            newItem.fields = fullItem.fields.map(field => {
              const newField = {
                id: field.id || "unnamed",
                title: field.title || field.label || "unnamed",
                fieldType: field.fieldType || sdk.ItemFieldType.Text,
                value: field.value || "",
                sectionId: field.sectionId
              };

              const builtInFieldIds = ["cardholder", "type", "number", "ccnum", "cvv", "expiry"];

              if (field.id === "type" || field.title.toLowerCase().includes("type")) {
                newField.fieldType = sdk.ItemFieldType.CreditCardType;
                const cardTypeMap = {
                  "mc": "Mastercard",
                  "visa": "Visa",
                  "amex": "American Express",
                  "discover": "Discover"
                };
                newField.value = cardTypeMap[field.value.toLowerCase()] || field.value || "Unknown";
              }

              if (field.id === "expiry" || field.title.toLowerCase().includes("expiry") || field.title.toLowerCase().includes("expiration")) {
                newField.fieldType = sdk.ItemFieldType.MonthYear;
                let expiryValue = field.value || "";
                if (expiryValue) {
                  if (/^\d{2}\/\d{4}$/.test(expiryValue)) {
                    newField.value = expiryValue;
                  } else if (/^\d{2}-\d{4}$/.test(expiryValue)) {
                    newField.value = expiryValue.replace('-', '/');
                  } else if (/^\d{2}\d{2}$/.test(expiryValue)) {
                    newField.value = `${expiryValue.slice(0, 2)}/20${expiryValue.slice(2)}`;
                  } else if (/^\d{2}\/\d{2}$/.test(expiryValue)) {
                    newField.value = `${expiryValue.slice(0, 2)}/20${expiryValue.slice(3)}`;
                  } else {
                    newField.value = "01/1970";
                  }
                } else {
                  newField.value = "01/1970";
                }
              }

              if (field.id === "number" || field.id === "ccnum" || field.title.toLowerCase().includes("number")) {
                newField.fieldType = sdk.ItemFieldType.CreditCardNumber;
              }

              if (field.id === "cvv" || field.title.toLowerCase().includes("verification")) {
                newField.fieldType = sdk.ItemFieldType.Concealed;
              }

              if (field.id === "pin" || field.title.toLowerCase().includes("pin")) {
                newField.fieldType = sdk.ItemFieldType.Concealed;
              }

              if (!newField.sectionId && !builtInFieldIds.includes(newField.id)) {
                newField.sectionId = "add more";
              }

              return newField;
            });
          }

          if (item.fields && item.fields.length > 0 && newItem.category !== sdk.ItemCategory.CreditCard) {
            newItem.fields = item.fields.map(field => {
              const newField = {
                id: field.id || "unnamed",
                title: field.title || field.label || "unnamed",
                fieldType: field.fieldType === sdk.ItemFieldType.Text ? sdk.ItemFieldType.Text :
                          field.fieldType === sdk.ItemFieldType.Concealed ? sdk.ItemFieldType.Concealed :
                          field.fieldType === sdk.ItemFieldType.Totp ? sdk.ItemFieldType.Totp :
                          field.fieldType === sdk.ItemFieldType.Address ? sdk.ItemFieldType.Address :
                          field.fieldType === sdk.ItemFieldType.SshKey ? sdk.ItemFieldType.SshKey :
                          field.fieldType === sdk.ItemFieldType.Date ? sdk.ItemFieldType.Date :
                          field.fieldType === sdk.ItemFieldType.MonthYear ? sdk.ItemFieldType.MonthYear :
                          field.fieldType === sdk.ItemFieldType.Email ? sdk.ItemFieldType.Email :
                          field.fieldType === sdk.ItemFieldType.Phone ? sdk.ItemFieldType.Phone :
                          field.fieldType === sdk.ItemFieldType.Url ? sdk.ItemFieldType.Url :
                          field.fieldType === sdk.ItemFieldType.Menu ? sdk.ItemFieldType.Menu :
                          sdk.ItemFieldType.Text,
                value: field.value || "",
                sectionId: field.sectionId
              };

              if (field.fieldType === sdk.ItemFieldType.Address && field.details && field.details.content) {
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
              } else if (field.fieldType === sdk.ItemFieldType.SshKey && field.details && field.details.content) {
                newField.value = field.details.content.privateKey || field.value || "";
              } else if (field.fieldType === sdk.ItemFieldType.Totp) {
                const totpValue = field.value || field.details?.content?.totp || "";
                const isValidTotpUri = totpValue.startsWith("otpauth://totp/");
                const isPotentialTotpSeed = /^[A-Z2-7]{16,32}$/i.test(totpValue);
                if (isValidTotpUri || isPotentialTotpSeed) {
                  newField.value = totpValue;
                } else {
                  newField.fieldType = sdk.ItemFieldType.Text;
                  newField.value = totpValue;
                }
              } else if (field.fieldType === sdk.ItemFieldType.Date || field.fieldType === sdk.ItemFieldType.MonthYear) {
                newField.value = field.value || "";
              }

              if (newField.sectionId === undefined && newField.id !== "username" && newField.id !== "password" && newField.fieldType !== sdk.ItemFieldType.Totp) {
                newField.sectionId = "add more";
              }
              return newField;
            });
          } else if (item.category === sdk.ItemCategory.SecureNote) {
            newItem.notes = item.notes || "Migrated Secure Note";
          }

          const referencedSectionIds = newItem.fields ? [...new Set(newItem.fields.map(field => field.sectionId).filter(id => id !== undefined))] : [];
          newItem.sections = [];
          if (item.sections && item.sections.length > 0) {
            const sourceSections = item.sections
              .filter(section => referencedSectionIds.includes(section.id) || (section.title && section.title.trim() !== ""))
              .map(section => ({ id: section.id, title: section.title || "" }));
            newItem.sections.push(...sourceSections);
          }
          if (referencedSectionIds.includes("add more") && !newItem.sections.some(section => section.id === "add more")) {
            newItem.sections.push({ id: "add more", title: "" });
          }
          if (newItem.sections.length === 0 && referencedSectionIds.length === 0) {
            delete newItem.sections;
          }
          if (item.tags && item.tags.length > 0) {
            newItem.tags = item.tags;
          }
          if (item.websites && item.websites.length > 0) {
            newItem.websites = item.websites.map(website => ({
              url: website.url || website.href || "",
              label: website.label || "website",
              autofillBehavior: website.autofillBehavior || sdk.AutofillBehavior.AnywhereOnWebsite
            }));
          }

          let createdItem = await retryWithBackoff(() => destSDK.client.items.create(newItem));
          const fetchedItem = await retryWithBackoff(() => destSDK.client.items.get(newVaultId, createdItem.id));

          if (item.files && item.files.length > 0) {
            const fileAttachPromises = item.files.map(file => {
              const fileName = file.name;
              const fileContent = file.content;
              const fileSectionId = newItem.sections && newItem.sections.find(section => section.id === file.sectionId)
                ? file.sectionId
                : (newItem.sections && newItem.sections[0]?.id) || "unnamed-section";
              const fileFieldId = file.fieldId || `${fileName}-${Date.now()}`;
              if (fileName && fileContent) {
                return retryWithBackoff(() => destSDK.client.items.files.attach(createdItem, {
                  name: fileName,
                  content: fileContent instanceof Uint8Array ? fileContent : new Uint8Array(fileContent),
                  sectionId: fileSectionId,
                  fieldId: fileFieldId
                }));
              }
              return Promise.resolve();
            });
            await Promise.all(fileAttachPromises);
          }

          processedItems++;
          migrationResults.push({ id: item.id, title: item.title, success: true, progress: (processedItems / items.length) * 100 });
          logEntry.itemResults.push({ id: item.id, title: item.title, success: true });
          console.log(`Successfully migrated item ${item.id} (${item.title}) in vault ${vaultId}`);
          migrationLog.push(`[INFO] Successfully migrated item ${item.id} (${item.title}) in vault ${vaultId}`);
          vaultLogs[vaultId].push(`[INFO] Successfully migrated item ${item.id} (${item.title})`);
        } catch (error) {
          processedItems++;
          console.error(`Error migrating item ${item.id} in vault ${vaultId}: ${error.message}`);
          migrationResults.push({ id: item.id, title: item.title, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
          logEntry.errors.push(`Item ${item.id}: ${error.message}`);
          logEntry.itemResults.push({ id: item.id, title: item.title, success: false, error: error.message });
          migrationLog.push(`[ERROR] Error migrating item ${item.id} in vault ${vaultId}: ${error.message}`);
          vaultLogs[vaultId].push(`[ERROR] Error migrating item ${item.id}: ${error.message}`);
        }
      }

      // Get destination item count
      const destItemCount = await getVaultItemCount(newVaultId, destToken);
      logEntry.destItemCount = destItemCount;
      logEntry.status = 'completed';
      console.log(`Vault ${vaultId} (${vaultName}) destination item count: ${destItemCount}`);
      migrationLog.push(`[INFO] Vault ${vaultId} (${vaultName}) destination item count: ${destItemCount}`);
      vaultLogs[vaultId].push(`[INFO] Destination item count: ${destItemCount}`);

      // Log item count comparison
      if (sourceItemCount === destItemCount) {
        console.log(`Vault ${vaultId} (${vaultName}): Successfully migrated ${sourceItemCount} items`);
        migrationLog.push(`[INFO] Vault ${vaultId} (${vaultName}): Successfully migrated ${sourceItemCount} items`);
        vaultLogs[vaultId].push(`[INFO] Successfully migrated ${sourceItemCount} items`);
      } else {
        console.error(`Vault ${vaultId} (${vaultName}): Item count mismatch - Source: ${sourceItemCount}, Destination: ${destItemCount}`);
        migrationLog.push(`[ERROR] Vault ${vaultId} (${vaultName}): Item count mismatch - Source: ${sourceItemCount}, Destination: ${destItemCount}`);
        vaultLogs[vaultId].push(`[ERROR] Item count mismatch - Source: ${sourceItemCount}, Destination: ${destItemCount}`);
      }

      migrationLog.push(JSON.stringify(logEntry, null, 2));
      vaultLogs[vaultId].push(JSON.stringify(logEntry, null, 2));
      console.log(`Completed migration for vault ${vaultId} (${vaultName})`);
      migrationLog.push(`[INFO] Completed migration for vault ${vaultId} (${vaultName})`);
      vaultLogs[vaultId].push(`[INFO] Completed migration`);
      return { itemsLength: items.length, migrationResults, sourceItemCount, destItemCount };
    } catch (error) {
      console.error(`Error migrating vault ${vaultId}: ${error.message}`);
      migrationLog.push(`[ERROR] Vault ${vaultId} (${vaultName}): Failed to migrate - ${error.message}`);
      vaultLogs[vaultId].push(`[ERROR] Failed to migrate: ${error.message}`);
      logEntry.status = 'failed';
      logEntry.errors.push(`Vault migration: ${error.message}`);
      migrationLog.push(JSON.stringify(logEntry, null, 2));
      vaultLogs[vaultId].push(JSON.stringify(logEntry, null, 2));
      throw error;
    }
  }

  // Migrate a single vault
  app.post('/migration/migrate-vault', async (req, res) => {
    const { vaultId, vaultName, sourceToken, destToken } = req.body;
    if (!vaultId || !vaultName || !sourceToken || !destToken) {
      console.error('Vault ID, vault name, source token, and destination token are required');
      migrationLog.push(`[ERROR] Vault ID, vault name, source token, and destination token are required`);
      return res.status(400).json({ success: false, message: 'Vault ID, vault name, source token, and destination token are required' });
    }

    try {
      const sourceSDK = new OnePasswordSDK(sourceToken);
      await sourceSDK.initializeClient();
      const destSDK = new OnePasswordSDK(destToken);
      await destSDK.initializeClient();

      const { itemsLength, migrationResults, sourceItemCount, destItemCount } = await migrateVault(vaultId, vaultName, sourceToken, destToken, sourceSDK, destSDK, () => isMigrationCancelled);

      const failedItems = migrationResults.filter(result => !result.success);
      if (failedItems.length > 0 || sourceItemCount !== destItemCount) {
        console.log(`Vault "${vaultName}" migration completed with ${failedItems.length} failures out of ${itemsLength} items. Item counts - Source: ${sourceItemCount}, Destination: ${destItemCount}`);
        migrationLog.push(`[INFO] Vault "${vaultName}" migration completed with ${failedItems.length} failures out of ${itemsLength} items. Item counts - Source: ${sourceItemCount}, Destination: ${destItemCount}`);
        res.json({
          success: false,
          message: `Vault "${vaultName}" migration completed with ${failedItems.length} failures out of ${itemsLength} items. Item counts - Source: ${sourceItemCount}, Destination: ${destItemCount}`,
          results: migrationResults
        });
      } else {
        console.log(`Successfully migrated vault "${vaultName}" with ${itemsLength} items`);
        migrationLog.push(`[INFO] Successfully migrated vault "${vaultName}" with ${itemsLength} items`);
        res.json({ success: true, message: `Successfully migrated vault "${vaultName}" with ${itemsLength} items`, results: migrationResults });
      }
    } catch (error) {
      console.error(`Failed to migrate vault: ${error.message}`);
      migrationLog.push(`[ERROR] Failed to migrate vault: ${error.message}`);
      res.status(500).json({ success: false, message: `Failed to migrate vault: ${error.message}` });
    }
  });

  // Migrate multiple or all vaults with Server-Sent Events
  app.get('/migration/migrate-all-vaults', async (req, res) => {
    const { sourceToken, destToken, vaults } = req.query;
    let selectedVaults;
    try {
      selectedVaults = vaults ? JSON.parse(decodeURIComponent(vaults)) : null;
    } catch (error) {
      console.error(`Failed to parse vaults query: ${error.message}`);
      migrationLog.push(`[ERROR] Failed to parse vaults query: ${error.message}`);
      selectedVaults = null;
    }

    if (!sourceToken || !destToken) {
      console.error('Source token and destination token are required');
      migrationLog.push(`[ERROR] Source token and destination token are required`);
      res.write(`data: ${JSON.stringify({ success: false, message: 'Source token and destination token are required', finished: true })}\n\n`);
      res.end();
      return;
    }

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.flushHeaders();

    const keepAliveInterval = setInterval(() => {
      res.write(': keep-alive\n\n');
    }, 15000);

    isMigrationCancelled = false;
    console.log('Starting migration of all vaults');
    migrationLog.push(`[INFO] Starting migration of all vaults`);

    try {
      const sourceSDK = new OnePasswordSDK(sourceToken);
      await sourceSDK.initializeClient();
      const destSDK = new OnePasswordSDK(destToken);
      await destSDK.initializeClient();

      let vaultsToMigrate;
      if (selectedVaults && selectedVaults.length > 0) {
        vaultsToMigrate = selectedVaults.map(v => ({ id: v.vaultId, name: v.vaultName }));
      } else {
        const allVaults = await sourceSDK.listVaults();
        vaultsToMigrate = allVaults;
      }

      const totalVaults = vaultsToMigrate.length;
      let completedVaults = 0;
      const migrationResults = [];

      for (const vault of vaultsToMigrate) {
        if (isMigrationCancelled) {
          console.log('Migration cancelled by user');
          migrationLog.push(`[INFO] Migration cancelled by user`);
          res.write(`data: ${JSON.stringify({ success: false, message: 'Migration cancelled by user', results: migrationResults })}\n\n`);
          clearInterval(keepAliveInterval);
          res.end();
          return;
        }

        const newVaultName = `${vault.name} (Migrated)`;
        try {
          const { itemsLength, migrationResults: vaultResults, sourceItemCount, destItemCount } = await migrateVault(vault.id, newVaultName, sourceToken, destToken, sourceSDK, destSDK, () => isMigrationCancelled);
          const failedItems = vaultResults.filter(result => !result.success);
          let outcome;
          if (failedItems.length > 0 || sourceItemCount !== destItemCount) {
            outcome = {
              vaultId: vault.id,
              vaultName: vault.name,
              success: false,
              message: `Vault "${vault.name}" migration completed with ${failedItems.length} failures out of ${itemsLength} items. Item counts - Source: ${sourceItemCount}, Destination: ${destItemCount}`,
              results: vaultResults,
              sourceItemCount,
              destItemCount
            };
            console.log(`Vault "${vault.name}" migration completed with ${failedItems.length} failures out of ${itemsLength} items`);
            migrationLog.push(`[INFO] Vault "${vault.name}" migration completed with ${failedItems.length} failures out of ${itemsLength} items`);
          } else {
            outcome = {
              vaultId: vault.id,
              vaultName: vault.name,
              success: true,
              message: `Successfully migrated vault "${vault.name}" with ${itemsLength} items`,
              results: vaultResults,
              sourceItemCount,
              destItemCount
            };
            console.log(`Successfully migrated vault "${vault.name}" with ${itemsLength} items`);
            migrationLog.push(`[INFO] Successfully migrated vault "${vault.name}" with ${itemsLength} items`);
          }
          migrationResults.push(outcome);
          completedVaults++;
          const progress = (completedVaults / totalVaults) * 100;
          res.write(`data: ${JSON.stringify({ progress: progress, outcome: outcome })}\n\n`);
        } catch (error) {
          const outcome = {
            vaultId: vault.id,
            vaultName: vault.name,
            success: false,
            message: `Failed to migrate vault "${vault.name}": ${error.message}`
          };
            console.log(`Failed to migrate vault "${vault.name}": ${error.message}`);
            migrationLog.push(`[ERROR] Failed to migrate vault "${vault.name}": ${error.message}`);
            migrationResults.push(outcome);
            completedVaults++;
            const progress = (completedVaults / totalVaults) * 100;
            res.write(`data: ${JSON.stringify({ progress: progress, outcome: outcome })}\n\n`);
          }
        }

        const failedVaults = migrationResults.filter(result => !result.success);
if (failedVaults.length > 0) {
  console.log(`Migration completed with ${failedVaults.length} vault failures out of ${vaultsToMigrate.length} vaults`);
  migrationLog.push(`[INFO] Migration completed with ${failedVaults.length} vault failures out of ${vaultsToMigrate.length} vaults`);
  res.write(`data: ${JSON.stringify({ success: false, message: `Migration completed with ${failedVaults.length} vault failures out of ${vaultsToMigrate.length} vaults`, results: migrationResults, finished: true })}\n\n`);
} else {
  console.log(`Successfully migrated all ${vaultsToMigrate.length} vaults`);
  migrationLog.push(`[INFO] Successfully migrated all ${vaultsToMigrate.length} vaults`);
  res.write(`data: ${JSON.stringify({ success: true, message: `Successfully migrated all ${vaultsToMigrate.length} vaults`, results: migrationResults, finished: true })}\n\n`);
}
clearInterval(keepAliveInterval);
res.end();
} catch (error) {
  console.error(`Failed to migrate vaults: ${error.message}`);
  migrationLog.push(`[ERROR] Failed to migrate vaults: ${error.message}`);
  res.write(`data: ${JSON.stringify({ success: false, message: `Failed to migrate vaults: ${error.message}`, finished: true })}\n\n`);
  clearInterval(keepAliveInterval);
  res.end();
}
    });

    // Endpoint to download accumulated migration log
    app.get('/migration/download-log', (req, res) => {
      const logContent = migrationLog.join('\n');
      console.log('Serving accumulated migration log for download');
      migrationLog.push(`[INFO] Accumulated migration log downloaded`);
      res.setHeader('Content-Type', 'text/plain');
      res.setHeader('Content-Disposition', 'attachment; filename=migration-log.txt');
      res.send(logContent);
    });

    // Endpoint to download individual vault log
    app.get('/migration/download-vault-log/:vaultId', (req, res) => {
      const { vaultId } = req.params;
      if (!vaultLogs[vaultId]) {
        console.error(`No log found for vault ${vaultId}`);
        migrationLog.push(`[ERROR] No log found for vault ${vaultId}`);
        return res.status(404).send('No log found for this vault');
      }
      const logContent = vaultLogs[vaultId].join('\n');
      console.log(`Serving log for vault ${vaultId}`);
      migrationLog.push(`[INFO] Log for vault ${vaultId} downloaded`);
      res.setHeader('Content-Type', 'text/plain');
      res.setHeader('Content-Disposition', `attachment; filename=vault-${vaultId}-log.txt`);
      res.send(logContent);
    });

    // Custom class to handle 1Password SDK interactions
    class OnePasswordSDK {
      constructor(token) {
        this.token = token;
        this.client = null;
      }

      async initializeClient() {
        if (!this.token) {
          console.error('Service account token is required');
          migrationLog.push(`[ERROR] Service account token is required`);
          throw new Error('Service account token is required.');
        }
        try {
          console.log('Initializing 1Password SDK client');
          migrationLog.push(`[INFO] Initializing 1Password SDK client`);
          this.client = await sdk.createClient({
            auth: this.token,
            integrationName: "1Password Vault Migration Tool",
            integrationVersion: "1.0.0",
          });
        } catch (error) {
          console.error(`Failed to initialize client: ${error.message}`);
          migrationLog.push(`[ERROR] Failed to initialize client: ${error.message}`);
          throw new Error(`Failed to initialize client: ${error.message}`);
        }
      }

      async listVaults() {
        try {
          if (!this.client) await this.initializeClient();
          const vaults = await this.client.vaults.list(); // Replace listAll with list
          const vaultList = vaults.map(vault => ({ id: vault.id, name: vault.title }));
          console.log(`Listed ${vaultList.length} vaults`);
          migrationLog.push(`[INFO] Listed ${vaultList.length} vaults`);
          return vaultList;
        } catch (error) {
          console.error(`Failed to list vaults: ${error.message}`);
          migrationLog.push(`[ERROR] Failed to list vaults: ${error.message}`);
          throw new Error(`Failed to list vaults: ${error.message}`);
        }
      }

      async listVaultItems(vaultId) {
  try {
    if (!this.client) await this.initializeClient();
    console.log(`Listing items for vault ${vaultId}`);
    migrationLog.push(`[INFO] Listing items for vault ${vaultId}`);
    vaultLogs[vaultId] = vaultLogs[vaultId] || [];
    vaultLogs[vaultId].push(`[INFO] Listing items`);
    const itemOverviews = await this.client.items.list(vaultId); // Use list instead of listAll
    const itemSummaries = itemOverviews.map(item => ({
      id: item.id,
      title: item.title,
      category: item.category
    }));

    const limit = pLimit(ITEM_CONCURRENCY_LIMIT);
    const itemPromises = itemSummaries.map(summary =>
      limit(async () => {
        const fullItem = await retryWithBackoff(() => this.client.items.get(vaultId, summary.id));
        const websites = fullItem.urls || fullItem.websites || fullItem.websiteUrls || [];
        const itemData = {
          id: fullItem.id,
          title: fullItem.title,
          category: fullItem.category,
          vaultId: fullItem.vaultId,
          fields: fullItem.fields || [],
          sections: fullItem.sections || [],
          tags: fullItem.tags || [],
          websites: websites,
          notes: fullItem.notes || ""
        };

        if (itemData.fields) {
          itemData.fields = itemData.fields.map(field => {
            if (field.fieldType === sdk.ItemFieldType.Address && field.details && field.details.content) {
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
            } else if (field.fieldType === sdk.ItemFieldType.SshKey && field.details && field.details.content) {
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

        if (fullItem.files && fullItem.files.length > 0) {
          const filePromises = fullItem.files.map(file =>
            retryWithBackoff(() => this.client.items.files.read(vaultId, fullItem.id, file.attributes))
              .then(fileContent => {
                return { name: file.attributes.name, content: fileContent, sectionId: file.sectionId, fieldId: file.fieldId };
              })
              .catch(() => null)
          );
          itemData.files = (await Promise.all(filePromises)).filter(f => f !== null);
        }

        if (fullItem.category === sdk.ItemCategory.Document && fullItem.document) {
          const documentContent = await retryWithBackoff(() => this.client.items.files.read(vaultId, fullItem.id, fullItem.document));
          itemData.document = { name: fullItem.document.name, content: documentContent };
        }

        return itemData;
      })
    );

    const items = await Promise.all(itemPromises);
    console.log(`Listed ${items.length} items for vault ${vaultId}`);
    migrationLog.push(`[INFO] Listed ${items.length} items for vault ${vaultId}`);
    vaultLogs[vaultId].push(`[INFO] Listed ${items.length} items`);
    return items;
  } catch (error) {
    console.error(`Failed to list items for vault ${vaultId}: ${error.message}`);
    migrationLog.push(`[ERROR] Failed to list items for vault ${vaultId}: ${error.message}`);
    vaultLogs[vaultId].push(`[ERROR] Failed to list items: ${error.message}`);
    throw new Error(`Failed to list items for vault ${vaultId}: ${error.message}`);
  }
}
    }

    // Start the HTTPS server
    const PORT = 3001;
    const attrs = [{ name: 'commonName', value: 'localhost' }];
    const opts = { keySize: 2048, algorithm: 'sha256', days: 365 };

    selfsigned.generate(attrs, opts, (err, pems) => {
      if (err) {
        console.error(`Failed to generate self-signed certificate: ${err.message}`);
        migrationLog.push(`[ERROR] Failed to generate self-signed certificate: ${err.message}`);
        return;
      }

      const options = {
        key: pems.private,
        cert: pems.cert,
      };

      https.createServer(options, app).listen(PORT, () => {
        console.log(`Server started on port ${PORT}`);
        migrationLog.push(`[INFO] Server started on port ${PORT}`);
      });
    });
  });