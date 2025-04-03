const sdk = require('@1password/sdk');
const { execSync } = require('child_process');
const express = require('express');
const bodyParser = require('body-parser');
const session = require('express-session');
const path = require('path');
const https = require('https');
const selfsigned = require('selfsigned');
const app = express();

// Import p-limit with fallback in case of import failure
let pLimit;
try {
  const pLimitModule = require('p-limit');
  pLimit = pLimitModule.default || pLimitModule;
  console.log('p-limit loaded successfully:', typeof pLimit);
} catch (error) {
  console.error('Failed to load p-limit:', error.message);
  pLimit = (limit) => (fn) => fn();
}

// Define concurrency limits for vault and item processing
const VAULT_CONCURRENCY_LIMIT = 2; // Limit to 2 vaults processed concurrently
const ITEM_CONCURRENCY_LIMIT = 1; // Process items one at a time within a vault

app.set('views', path.join(__dirname, 'views'));
app.set('view engine', 'ejs');

app.use(express.static('public'));
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());

// Configure session middleware for storing user data
app.use(session({
  secret: 'your-secret-key',
  resave: false,
  saveUninitialized: false,
  cookie: { secure: false, httpOnly: true, path: '/', maxAge: 24 * 60 * 60 * 1000 }
}));

// Handle root route to display welcome page
app.get('/', (req, res) => {
  res.render('welcome', { currentPage: 'welcome' });
});

// Render migration page
app.get('/migration', (req, res) => {
  res.render('migration', { error: null, currentPage: 'migration' });
});

// Endpoint to list vaults from 1Password using the provided service token
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
    console.error('Error listing vaults:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Flag to track migration cancellation status
let isMigrationCancelled = false;

// Endpoint to cancel an ongoing migration
app.post('/migration/cancel', (req, res) => {
  console.log('Cancellation requested');
  isMigrationCancelled = true;
  res.json({ success: true, message: 'Migration cancellation requested' });
});

// Utility function to retry operations with exponential backoff for conflicts or rate limits
const retryWithBackoff = async (fn, maxRetries = 3, baseDelay = 1000) => {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      if (
        (error.message.includes('data conflict') || error.message.includes('rate limit')) &&
        attempt < maxRetries
      ) {
        const delay = baseDelay * Math.pow(2, attempt - 1); // Calculate delay with exponential backoff
        console.log(`Conflict or rate limit hit, retrying (${attempt}/${maxRetries}) after ${delay}ms...`);
        await new Promise(resolve => setTimeout(resolve, delay));
      } else {
        throw error;
      }
    }
  }
};

// Function to migrate a single vault and its items
async function migrateVault(vaultId, vaultName, sourceToken, destToken, sourceSDK, destSDK, isCancelled) {
  const destEnv = { ...process.env, OP_SERVICE_ACCOUNT_TOKEN: destToken };
  const createVaultCommand = `op vault create "${vaultName}" --format json`;
  const newVaultOutput = execSync(createVaultCommand, { env: destEnv, encoding: 'utf8' });
  const newVault = JSON.parse(newVaultOutput);
  const newVaultId = newVault.id;

  const items = await sourceSDK.listVaultItems(vaultId);
  console.log(`Fetched ${items.length} items from source vault "${vaultName}"`);

  const migrationResults = [];
  let processedItems = 0;

  // Iterate through items sequentially to prevent conflicts
  for (const item of items) {
    if (isCancelled()) {
      console.log(`Migration cancelled during vault "${vaultName}"`);
      return { itemsLength: items.length, migrationResults };
    }

    console.log(`Migrating item "${item.title}" (ID: ${item.id})...`);
    const newItem = {
      title: item.title,
      category: item.category || sdk.ItemCategory.Login,
      vaultId: newVaultId
    };

    try {
      if (item.category === 'Document') {
        const fullItem = await retryWithBackoff(() => sourceSDK.client.items.get(vaultId, item.id));
        if (fullItem.category !== 'Document' || !fullItem.document) {
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

      if (item.fields && item.fields.length > 0) {
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
            console.log(`Source TOTP field for "${item.title}": value=${totpValue}`);
            const isValidTotpUri = totpValue.startsWith("otpauth://totp/");
            const isPotentialTotpSeed = /^[A-Z2-7]{16,32}$/i.test(totpValue);
            if (isValidTotpUri || isPotentialTotpSeed) {
              newField.value = totpValue;
              console.log(`TOTP field prepared for "${item.title}":`, JSON.stringify(newField, null, 2));
            } else {
              console.warn(`TOTP field for item "${item.title}" contains invalid value: ${totpValue}. Converting to Text.`);
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
      console.log(`Created item "${item.title}" in destination vault "${newVaultId}"`);

      const fetchedItem = await retryWithBackoff(() => destSDK.client.items.get(newVaultId, createdItem.id));
      const totpField = fetchedItem.fields.find(f => f.fieldType === sdk.ItemFieldType.Totp);
      if (totpField) {
        console.log(`TOTP field in destination for "${item.title}":`, JSON.stringify(totpField, null, 2));
      } else {
        console.error(`TOTP field not found in destination for "${item.title}" after migration`);
      }

      // Handle file attachments for items that include files
      if (item.files && item.files.length > 0) {
        console.log(`Item "${item.title}" has ${item.files.length} files to attach:`, item.files);
        const fileAttachPromises = item.files.map(file => {
          const fileName = file.name;
          const fileContent = file.content;
          const fileSectionId = newItem.sections && newItem.sections.find(section => section.id === file.sectionId)
            ? file.sectionId
            : (newItem.sections && newItem.sections[0]?.id) || "unnamed-section";
          const fileFieldId = file.fieldId || `${fileName}-${Date.now()}`;
          if (fileName && fileContent) {
            console.log(`Attaching file "${fileName}" to item "${item.title}" in section "${fileSectionId}" with field ID "${fileFieldId}"`);
            return retryWithBackoff(() => destSDK.client.items.files.attach(createdItem, {
              name: fileName,
              content: fileContent instanceof Uint8Array ? fileContent : new Uint8Array(fileContent),
              sectionId: fileSectionId,
              fieldId: fileFieldId
            }))
            .then(() => {
              console.log(`Successfully attached file "${fileName}" to item "${item.title}"`);
            })
            .catch(err => {
              console.error(`Failed to attach file "${fileName}" to item "${item.title}": ${err.message}`);
              throw err;
            });
          }
          console.log(`Skipping file attachment for "${item.title}": missing fileName or fileContent`);
          return Promise.resolve();
        });
        await Promise.all(fileAttachPromises);
      } else {
        console.log(`No files to attach for item "${item.title}"`);
      }

      processedItems++;
      migrationResults.push({ id: item.id, title: item.title, success: true, progress: (processedItems / items.length) * 100 });
    } catch (error) {
      console.error(`Error migrating item "${item.title}" (ID: ${item.id}):`, error.message);
      processedItems++;
      migrationResults.push({ id: item.id, title: item.title, success: false, error: error.message, progress: (processedItems / items.length) * 100 });
    }
  }

  return { itemsLength: items.length, migrationResults };
}

// Endpoint to migrate a single vault
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
    console.error('Error migrating vault:', error);
    res.status(500).json({ success: false, message: `Failed to migrate vault: ${error.message}` });
  }
});

// Endpoint to migrate multiple or all vaults
app.post('/migration/migrate-all-vaults', async (req, res) => {
  const { sourceToken, destToken, vaults: selectedVaults } = req.body;
  if (!sourceToken || !destToken) {
    return res.status(400).json({ success: false, message: 'Source token and destination token are required' });
  }

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
      console.log(`Fetched ${allVaults.length} vaults from source`);
      vaultsToMigrate = allVaults;
    }

    const migrationResults = [];
    const limit = pLimit(VAULT_CONCURRENCY_LIMIT);
    const vaultPromises = vaultsToMigrate.map(vault =>
      limit(async () => {
        if (isMigrationCancelled) {
          console.log('Migration cancelled by user');
          return {
            vaultId: vault.id,
            vaultName: vault.name,
            success: false,
            message: 'Migration cancelled by user'
          };
        }

        console.log(`Migrating vault "${vault.name}" (ID: ${vault.id})...`);
        const newVaultName = `${vault.name} (Migrated)`;

        try {
          const { itemsLength, migrationResults: vaultResults } = await migrateVault(vault.id, newVaultName, sourceToken, destToken, sourceSDK, destSDK, () => isMigrationCancelled);
          const failedItems = vaultResults.filter(result => !result.success);
          if (failedItems.length > 0) {
            return {
              vaultId: vault.id,
              vaultName: vault.name,
              success: false,
              message: `Vault "${vault.name}" migration completed with ${failedItems.length} failures out of ${itemsLength} items`,
              results: vaultResults
            };
          } else {
            return {
              vaultId: vault.id,
              vaultName: vault.name,
              success: true,
              message: `Successfully migrated vault "${vault.name}" with ${itemsLength} items`,
              results: vaultResults
            };
          }
        } catch (error) {
          console.error(`Error migrating vault "${vault.name}":`, error.message);
          return {
            vaultId: vault.id,
            vaultName: vault.name,
            success: false,
            message: `Failed to migrate vault "${vault.name}": ${error.message}`
          };
        }
      })
    );

    const results = await Promise.all(vaultPromises);
    results.forEach(result => migrationResults.push(result));

    const failedVaults = migrationResults.filter(result => !result.success);
    if (failedVaults.length > 0) {
      res.json({
        success: false,
        message: `Migration completed with ${failedVaults.length} vault failures out of ${vaultsToMigrate.length} vaults`,
        results: migrationResults
      });
    } else {
      res.json({ success: true, message: `Successfully migrated all ${vaultsToMigrate.length} vaults`, results: migrationResults });
    }
  } catch (error) {
    console.error('Error migrating vaults:', error);
    res.status(500).json({ success: false, message: `Failed to migrate vaults: ${error.message}` });
  }
});

// Custom SDK class for interacting with 1Password
class OnePasswordSDK {
  constructor(token) {
    this.token = token;
    this.client = null;
  }

  // Initialize the 1Password client with the provided token
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

  // Fetch all vaults from the 1Password account
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

  // Fetch all items within a specific vault
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
          console.log(`Fetched item "${summary.title}" (ID: ${summary.id}) from vault ${vaultId}`);
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
              if (field.fieldType === "Address" && field.details && field.details.content) {
                return { ...field, details: { content: { street: field.details.content.street || "", city: field.details.content.city || "", state: field.details.content.state || "", zip: field.details.content.zip || "", country: field.details.content.country || "" } } };
              } else if (field.fieldType === "SshKey" && field.details && field.details.content) {
                return { ...field, details: { content: { privateKey: field.details.content.privateKey || field.value || "", publicKey: field.details.content.publicKey || "", fingerprint: field.details.content.fingerprint || "", keyType: field.details.content.keyType || "" } } };
              } else if (field.fieldType === "Totp") {
                return { ...field, value: field.details?.content?.totp || field.value || "", details: field.details || {} };
              }
              return field;
            });
          }

          if (fullItem.files && fullItem.files.length > 0) {
            console.log(`Item "${summary.title}" has ${fullItem.files.length} files:`, fullItem.files);
            const filePromises = fullItem.files.map(file =>
              retryWithBackoff(() => this.client.items.files.read(vaultId, fullItem.id, file.attributes))
                .then(fileContent => {
                  console.log(`Successfully fetched file for item "${summary.title}":`, { name: file.attributes.name, contentLength: fileContent.length });
                  return { name: file.attributes.name, content: fileContent, sectionId: file.sectionId, fieldId: file.fieldId };
                })
                .catch(err => { console.error(`Failed to fetch file for ${summary.id}: ${err.message}`); return null; })
            );
            itemData.files = (await Promise.all(filePromises)).filter(f => f !== null);
            console.log(`After filtering, item "${summary.title}" has ${itemData.files.length} files:`, itemData.files);
          } else {
            console.log(`No files found for item "${summary.title}"`);
          }

          if (fullItem.category === 'Document' && fullItem.document) {
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

const PORT = 3001;
const attrs = [{ name: 'commonName', value: 'localhost' }];
const opts = { keySize: 2048, algorithm: 'sha256', days: 365 };

selfsigned.generate(attrs, opts, (err, pems) => {
  if (err) {
    console.error('Error generating cert:', err);
    return;
  }

  const options = {
    key: pems.private,
    cert: pems.cert,
  };

  https.createServer(options, app).listen(PORT, () => {
    console.log(`Server running on https://localhost:${PORT}`);
  });
});