const sdk = require('@1password/sdk');
const { execSync } = require('child_process');
const express = require('express');
const bodyParser = require('body-parser');
const session = require('express-session');
const path = require('path');
const https = require('https');
const selfsigned = require('selfsigned');
const app = express();

// Dynamically import p-limit for concurrency control
let pLimit;
async function loadPLimit() {
  try {
    const pLimitModule = await import('p-limit');
    pLimit = pLimitModule.default || pLimitModule;
  } catch (error) {
    // Fallback to no concurrency limit if p-limit fails
    pLimit = (limit) => (fn) => fn();
  }
}

// Start the app once p-limit is loaded
loadPLimit().then(() => {
  const VAULT_CONCURRENCY_LIMIT = 2; // Max vaults to process at once
  const ITEM_CONCURRENCY_LIMIT = 1; // Max items to process at once per vault

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
      return res.status(400).json({ success: false, error: 'Service token is required' });
    }
    try {
      const sdkInstance = new OnePasswordSDK(serviceToken);
      await sdkInstance.initializeClient();
      const vaults = await sdkInstance.listVaults();
      res.json({ success: true, vaults });
    } catch (error) {
      res.status(500).json({ success: false, error: error.message });
    }
  });

  let isMigrationCancelled = false;

  // Cancel an ongoing migration
  app.post('/migration/cancel', (req, res) => {
    isMigrationCancelled = true;
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
          await new Promise(resolve => setTimeout(resolve, delay));
        } else {
          throw error;
        }
      }
    }
  };

  // Migrate a single vault and its items
  async function migrateVault(vaultId, vaultName, sourceToken, destToken, sourceSDK, destSDK, isCancelled) {
    const destEnv = { ...process.env, OP_SERVICE_ACCOUNT_TOKEN: destToken };
    const createVaultCommand = `op vault create "${vaultName}" --format json`;
    const newVaultOutput = execSync(createVaultCommand, { env: destEnv, encoding: 'utf8' });
    const newVault = JSON.parse(newVaultOutput);
    const newVaultId = newVault.id;

    const items = await sourceSDK.listVaultItems(vaultId);
    const migrationResults = [];
    let processedItems = 0;

    for (const item of items) {
      if (isCancelled()) {
        return { itemsLength: items.length, migrationResults };
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
            throw new Error(`Item ${item.title} is not a Document or has no document`);
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
              fieldType: field.fieldType === "Text" ? sdk.ItemFieldType.Text :
                        field.fieldType === "Concealed" ? sdk.ItemFieldType.Concealed :
                        field.fieldType === "Totp" ? sdk.ItemFieldType.Totp :
                        field.fieldType === "Address" ? sdk.ItemFieldType.Address :
                        field.fieldType === "SshKey" ? sdk.ItemFieldType.SshKey :
                        field.fieldType === "Date" ? sdk.ItemFieldType.Date :
                        field.fieldType === "MonthYear" ? sdk.ItemFieldType.MonthYear :
                        field.fieldType === "Email" ? sdk.ItemFieldType.Email :
                        field.fieldType === "Phone" ? sdk.ItemFieldType.Phone :
                        field.fieldType === "Url" ? sdk.ItemFieldType.Url :
                        field.fieldType === "Menu" ? sdk.ItemFieldType.Menu :
                        sdk.ItemFieldType.Text,
              value: field.value || "",
              sectionId: field.sectionId
            };

            if (field.fieldType === "Address" && field.details && field.details.content) {
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
            } else if (field.fieldType === "SshKey" && field.details && field.details.content) {
              newField.value = field.details.content.privateKey || field.value || "";
            } else if (field.fieldType === "Totp") {
              const totpValue = field.value || field.details?.content?.totp || "";
              const isValidTotpUri = totpValue.startsWith("otpauth://totp/");
              const isPotentialTotpSeed = /^[A-Z2-7]{16,32}$/i.test(totpValue);
              if (isValidTotpUri || isPotentialTotpSeed) {
                newField.value = totpValue;
              } else {
                newField.fieldType = sdk.ItemFieldType.Text;
                newField.value = totpValue;
              }
            } else if (field.fieldType === "Date" || field.fieldType === "MonthYear") {
              newField.value = field.value || "";
            }

            if (newField.sectionId === undefined && newField.id !== "username" && newField.id !== "password" && newField.fieldType !== sdk.ItemFieldType.Totp) {
              newField.sectionId = "add more";
            }
            return newField;
          });
        } else if (item.category === "SecureNote") {
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
      } catch (error) {
        processedItems++;
        migrationResults.push({ id: item.id, title: item.title, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
      }
    }

    return { itemsLength: items.length, migrationResults };
  }

  // Migrate a single vault
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

      const { itemsLength, migrationResults } = await migrateVault(vaultId, vaultName, sourceToken, destToken, sourceSDK, destSDK, () => isMigrationCancelled);

      const failedItems = migrationResults.filter(result => !result.success);
      if (failedItems.length > 0) {
        res.json({
          success: false,
          message: `Vault "${vaultName}" migration completed with ${failedItems.length} failures out of ${itemsLength} items`,
          results: migrationResults
        });
      } else {
        res.json({ success: true, message: `Successfully migrated vault "${vaultName}" with ${itemsLength} items`, results: migrationResults });
      }
    } catch (error) {
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
      selectedVaults = null;
    }

    if (!sourceToken || !destToken) {
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
          res.write(`data: ${JSON.stringify({ success: false, message: 'Migration cancelled by user', results: migrationResults })}\n\n`);
          clearInterval(keepAliveInterval);
          res.end();
          return;
        }

        const newVaultName = `${vault.name} (Migrated)`;
        try {
          const { itemsLength, migrationResults: vaultResults } = await migrateVault(vault.id, newVaultName, sourceToken, destToken, sourceSDK, destSDK, () => isMigrationCancelled);
          const failedItems = vaultResults.filter(result => !result.success);
          let outcome;
          if (failedItems.length > 0) {
            outcome = {
              vaultId: vault.id,
              vaultName: vault.name,
              success: false,
              message: `Vault "${vault.name}" migration completed with ${failedItems.length} failures out of ${itemsLength} items`,
              results: vaultResults
            };
          } else {
            outcome = {
              vaultId: vault.id,
              vaultName: vault.name,
              success: true,
              message: `Successfully migrated vault "${vault.name}" with ${itemsLength} items`,
              results: vaultResults
            };
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
          migrationResults.push(outcome);
          completedVaults++;
          const progress = (completedVaults / totalVaults) * 100;
          res.write(`data: ${JSON.stringify({ progress: progress, outcome: outcome })}\n\n`);
        }
      }

      const failedVaults = migrationResults.filter(result => !result.success);
      if (failedVaults.length > 0) {
        res.write(`data: ${JSON.stringify({ success: false, message: `Migration completed with ${failedVaults.length} vault failures out of ${vaultsToMigrate.length} vaults`, results: migrationResults, finished: true })}\n\n`);
      } else {
        res.write(`data: ${JSON.stringify({ success: true, message: `Successfully migrated all ${vaultsToMigrate.length} vaults`, results: migrationResults, finished: true })}\n\n`);
      }
      clearInterval(keepAliveInterval);
      res.end();
    } catch (error) {
      res.write(`data: ${JSON.stringify({ success: false, message: `Failed to migrate vaults: ${error.message}`, finished: true })}\n\n`);
      clearInterval(keepAliveInterval);
      res.end();
    }
  });

  // Custom class to handle 1Password SDK interactions
  class OnePasswordSDK {
    constructor(token) {
      this.token = token;
      this.client = null;
    }

    async initializeClient() {
      if (!this.token) throw new Error('Service account token is required.');
      try {
        this.client = await sdk.createClient({
          auth: this.token,
          integrationName: "1Password Dashboard",
          integrationVersion: "1.0.0",
        });
      } catch (error) {
        throw new Error(`Failed to initialize client: ${error.message}`);
      }
    }

    async listVaults() {
      try {
        if (!this.client) await this.initializeClient();
        const vaultIterator = await this.client.vaults.listAll();
        const vaults = [];
        for await (const vault of vaultIterator) {
          vaults.push({ id: vault.id, name: vault.title });
        }
        return vaults;
      } catch (error) {
        throw new Error(`Failed to list vaults: ${error.message}`);
      }
    }

    async listVaultItems(vaultId) {
      try {
        if (!this.client) await this.initializeClient();
        const itemsIterator = await this.client.items.listAll(vaultId);
        const itemSummaries = [];
        for await (const item of itemsIterator) {
          itemSummaries.push({ id: item.id, title: item.title, category: item.category });
        }

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

        return await Promise.all(itemPromises);
      } catch (error) {
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
      return;
    }

    const options = {
      key: pems.private,
      cert: pems.cert,
    };

    https.createServer(options, app).listen(PORT, () => {});
  });
});