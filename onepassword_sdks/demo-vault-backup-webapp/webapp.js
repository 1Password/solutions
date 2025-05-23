const sdk = require('@1password/sdk');
const { execSync } = require('child_process');
const express = require('express');
const bodyParser = require('body-parser');
const session = require('express-session');
const path = require('path');
const crypto = require('crypto');
const fs = require('fs');
const multer = require('multer');
const argon2 = require('argon2');
const https = require('https');
const selfsigned = require('selfsigned');

// Set up multer for handling file uploads (used in restore endpoints)
const upload = multer({ dest: 'uploads/' });

// In-memory logs to track operations and errors
let backupLog = [];
let vaultLogs = {};

// Load p-limit for concurrency control, with a fallback if it fails
let pLimit;
try {
  const pLimitModule = require('p-limit');
  pLimit = pLimitModule.default || pLimitModule;
  console.log('p-limit loaded successfully:', typeof pLimit);
  backupLog.push('[INFO] p-limit loaded successfully');
} catch (error) {
  console.error('Failed to load p-limit:', error.message);
  backupLog.push(`[ERROR] Failed to load p-limit: ${error.message}`);
  pLimit = (limit) => (fn) => fn(); // No concurrency limit if p-limit fails
}

// Concurrency limits for vault and item operations
const VAULT_CONCURRENCY_LIMIT = 2;
const ITEM_CONCURRENCY_LIMIT = 1;

// Set up Express app with EJS templating and middleware
const app = express();
app.set('views', path.join(__dirname, 'views'));
app.set('view engine', 'ejs');
app.use(express.static('public'));
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());
app.use(session({
  secret: 'your-secret-key',
  resave: false,
  saveUninitialized: false,
  cookie: { secure: false, httpOnly: true, path: '/', maxAge: 24 * 60 * 60 * 1000 }
}));

// Basic routes for the UI
app.get('/', (req, res) => {
  res.render('welcome', { currentPage: 'welcome' });
});

app.get('/backup', (req, res) => {
  res.render('backup', { error: null, currentPage: 'backup' });
});

app.get('/restore', (req, res) => {
  res.render('restore', { error: null, currentPage: 'restore' });
});

// List vaults and their active item counts
app.post('/backup/list-vaults', async (req, res) => {
  const { serviceToken } = req.body;
  if (!serviceToken) {
    backupLog.push('[ERROR] Service token is required');
    return res.status(400).json({ success: false, error: 'Service token is required' });
  }
  try {
    const sdkInstance = new OnePasswordSDK(serviceToken);
    await sdkInstance.initializeClient();
    const vaults = await sdkInstance.listVaults();
    // Get active item counts for each vault, logging archived items if any
    const vaultsWithCounts = await Promise.all(vaults.map(async (vault) => {
      const count = await sdkInstance.getVaultItemCount(vault.id, vault.name);
      backupLog.push(`[INFO] Vault ${vault.id} (${vault.name}): ${count} active items`);
      return { ...vault, itemCount: count };
    }));
    res.json({ success: true, vaults: vaultsWithCounts });
  } catch (error) {
    console.error('Error listing vaults:', error.message);
    backupLog.push(`[ERROR] Failed to list vaults: ${error.message}`);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Back up selected vaults to an encrypted file
app.post('/backup/backup-vaults', async (req, res) => {
  const { serviceToken, vaults, passcode } = req.body;
  if (!serviceToken || !vaults || !passcode) {
    backupLog.push('[ERROR] Service token, vaults, and passcode are required');
    return res.status(400).json({ success: false, message: 'Service token, vaults, and passcode are required' });
  }
  if (passcode.length < 8) {
    backupLog.push('[ERROR] Passcode must be at least 8 characters long');
    return res.status(400).json({ success: false, message: 'Passcode must be at least 8 characters long' });
  }

  try {
    const sdkInstance = new OnePasswordSDK(serviceToken);
    await sdkInstance.initializeClient();

    // Generate keys for encryption and HMAC
    const systemKey = crypto.randomBytes(16);
    const encryptionKey = await argon2.hash(passcode, {
      salt: systemKey,
      type: argon2.argon2id,
      memoryCost: 65536,
      timeCost: 3,
      parallelism: 1,
      hashLength: 32,
      raw: true
    });
    const hmacKey = await argon2.hash(passcode + 'hmac', {
      salt: systemKey,
      type: argon2.argon2id,
      memoryCost: 65536,
      timeCost: 3,
      parallelism: 1,
      hashLength: 32,
      raw: true
    });
    const iv = crypto.randomBytes(16);

    const vaultsToBackup = vaults.map(v => ({ id: v.vaultId, name: v.vaultName }));
    const backupData = { vaults: [], systemKey: systemKey.toString('hex') };

    const totalVaults = vaultsToBackup.length;
    let processedVaults = 0;
    const backupResults = [];

    // Back up each vault with concurrency control
    const limit = pLimit(VAULT_CONCURRENCY_LIMIT);
    const vaultPromises = vaultsToBackup.map(vault =>
      limit(async () => {
        console.log(`Backing up vault "${vault.name}" (ID: ${vault.id})...`);
        backupLog.push(`[INFO] Backing up vault "${vault.name}" (ID: ${vault.id})`);
        const items = await sdkInstance.listVaultItems(vault.id);
        processedVaults++;
        const progress = (processedVaults / totalVaults) * 100;
        backupResults.push({
          vaultId: vault.id,
          vaultName: vault.name,
          progress: progress
        });
        return { id: vault.id, name: vault.name, items };
      })
    );

    backupData.vaults = await Promise.all(vaultPromises);

    // Encrypt the backup data and add HMAC
    const cipher = crypto.createCipheriv('aes-256-cbc', encryptionKey, iv);
    let encrypted = cipher.update(JSON.stringify(backupData), 'utf8', 'hex');
    encrypted += cipher.final('hex');
    const hmac = crypto.createHmac('sha256', hmacKey)
      .update(iv.toString('hex') + encrypted)
      .digest('hex');
    const encryptedBackup = { iv: iv.toString('hex'), data: encrypted, hmac };

    // Save the encrypted backup to a file
    const backupFilePath = path.join(__dirname, 'public', 'backup.1pbackup');
    fs.writeFileSync(backupFilePath, JSON.stringify(encryptedBackup));

    backupLog.push('[INFO] Backup file created successfully');
    res.json({ 
      success: true, 
      systemKey: systemKey.toString('hex'), 
      passcode, 
      filePath: '/backup.1pbackup',
      results: backupResults 
    });
  } catch (error) {
    console.error('Error backing up vaults:', error.message);
    backupLog.push(`[ERROR] Error backing up vaults: ${error.message}`);
    res.status(500).json({ success: false, message: error.message });
  }
});

// Save backup keys (passcode and systemKey) to a Secure Note
app.post('/backup/save-keys', async (req, res) => {
  const { serviceToken, systemKey, passcode } = req.body;
  if (!serviceToken || !systemKey || !passcode) {
    backupLog.push('[ERROR] Service token, system key, and passcode are required');
    return res.status(400).json({ success: false, message: 'Service token, system key, and passcode are required' });
  }

  try {
    const sdkInstance = new OnePasswordSDK(serviceToken);
    await sdkInstance.initializeClient();

    const vaultName = "Backup Keys";
    let vaultId;
    try {
      const createVaultCommand = `op vault create "${vaultName}" --format json`;
      const newVaultOutput = execSync(createVaultCommand, { env: { ...process.env, OP_SERVICE_ACCOUNT_TOKEN: serviceToken }, encoding: 'utf8' });
      vaultId = JSON.parse(newVaultOutput).id;

      // Attempt to grant view_items permission to Administrators group only
      const group = 'Administrators';
      const grantCommand = `op vault group grant --vault "${vaultId}" --group "${group}" --permissions view_items`;
      try {
        execSync(grantCommand, { env: { ...process.env, OP_SERVICE_ACCOUNT_TOKEN: serviceToken }, encoding: 'utf8' });
        backupLog.push(`[INFO] Granted view_items permission to ${group} for vault "${vaultName}" (ID: ${vaultId})`);
      } catch (grantError) {
        console.warn(`Failed to grant view_items permission to ${group} for vault "${vaultName}": ${grantError.message}`);
        backupLog.push(`[WARN] Failed to grant view_items permission to ${group} for vault "${vaultName}": ${grantError.message}`);
        // Continue execution instead of throwing an error
      }
    } catch (error) {
      backupLog.push(`[ERROR] Failed to create vault "${vaultName}": ${error.message}`);
      return res.status(403).json({ success: false, message: 'Service account lacks vault creation permission' });
    }

    const item = {
      title: `Backup Keys - ${new Date().toISOString().split('T')[0]}`,
      category: sdk.ItemCategory.SecureNote,
      vaultId: vaultId,
      fields: [
        { id: 'passcode', title: 'Passcode', fieldType: sdk.ItemFieldType.Concealed, value: passcode },
        { id: 'systemKey', title: 'System Key', fieldType: sdk.ItemFieldType.Text, value: systemKey }
      ],
      notes: 'Generated keys for 1Password backup'
    };
    await sdkInstance.createItem(vaultId, item);

    backupLog.push(`[INFO] Keys saved to vault "${vaultName}"`);
    res.json({ success: true, message: `Keys saved to vault "${vaultName}"` });
  } catch (error) {
    console.error('Error saving keys to 1Password:', error.message);
    backupLog.push(`[ERROR] Error saving keys to 1Password: ${error.message}`);
    res.status(500).json({ success: false, message: error.message });
  }
});

// List vaults from a backup file (decrypts and shows vault info)
app.post('/restore/list-vaults', upload.single('backupFile'), async (req, res) => {
  const { serviceToken, passcode, systemKey } = req.body;
  const backupFile = req.file;

  if (!serviceToken || !passcode || !systemKey || !backupFile) {
    backupLog.push('[ERROR] Service token, passcode, system key, and backup file are required');
    return res.status(400).json({ success: false, message: 'Service token, passcode, system key, and backup file are required' });
  }

  try {
    const sdkInstance = new OnePasswordSDK(serviceToken);
    await sdkInstance.initializeClient();

    // Read and decrypt the backup file
    const encryptedBackup = JSON.parse(fs.readFileSync(backupFile.path, 'utf8'));
    const iv = Buffer.from(encryptedBackup.iv, 'hex');
    const systemKeyBuffer = Buffer.from(systemKey, 'hex');
    const encryptionKey = await argon2.hash(passcode, {
      salt: systemKeyBuffer,
      type: argon2.argon2id,
      memoryCost: 65536,
      timeCost: 3,
      parallelism: 1,
      hashLength: 32,
      raw: true
    });
    const hmacKey = await argon2.hash(passcode + 'hmac', {
      salt: systemKeyBuffer,
      type: argon2.argon2id,
      memoryCost: 65536,
      timeCost: 3,
      parallelism: 1,
      hashLength: 32,
      raw: true
    });

    // Verify HMAC to ensure data integrity
    const computedHmac = crypto.createHmac('sha256', hmacKey)
      .update(encryptedBackup.iv + encryptedBackup.data)
      .digest('hex');
    if (computedHmac !== encryptedBackup.hmac) {
      backupLog.push('[ERROR] HMAC verification failed - data may have been tampered with');
      throw new Error('HMAC verification failed - data may have been tampered with');
    }

    const decipher = crypto.createDecipheriv('aes-256-cbc', encryptionKey, iv);
    let decrypted = decipher.update(encryptedBackup.data, 'hex', 'utf8');
    decrypted += decipher.final('utf8');
    const backupData = JSON.parse(decrypted);

    // Return vault list with item counts
    const vaults = backupData.vaults.map(vault => ({
      id: vault.id,
      name: vault.name,
      itemCount: vault.items.length
    }));

    fs.unlinkSync(backupFile.path);
    backupLog.push('[INFO] Successfully listed vaults from backup');
    res.json({ success: true, vaults });
  } catch (error) {
    console.error('Error listing vaults from backup:', error.message);
    backupLog.push(`[ERROR] Error listing vaults from backup: ${error.message}`);
    fs.unlinkSync(backupFile.path);
    res.status(500).json({ success: false, message: error.message });
  }
});

// Restore selected vaults from a backup file
app.post('/restore/restore-vaults', upload.single('backupFile'), async (req, res) => {
  const { serviceToken, passcode, systemKey, selectedVaults } = req.body;
  const backupFile = req.file;

  if (!serviceToken || !passcode || !systemKey || !backupFile || !selectedVaults) {
    backupLog.push('[ERROR] Service token, passcode, system key, backup file, and selected vaults are required');
    return res.status(400).json({ success: false, message: 'Service token, passcode, system key, backup file, and selected vaults are required' });
  }

  try {
    const sdkInstance = new OnePasswordSDK(serviceToken);
    await sdkInstance.initializeClient();

    // Decrypt the backup file
    const encryptedBackup = JSON.parse(fs.readFileSync(backupFile.path, 'utf8'));
    const iv = Buffer.from(encryptedBackup.iv, 'hex');
    const systemKeyBuffer = Buffer.from(systemKey, 'hex');
    const encryptionKey = await argon2.hash(passcode, {
      salt: systemKeyBuffer,
      type: argon2.argon2id,
      memoryCost: 65536,
      timeCost: 3,
      parallelism: 1,
      hashLength: 32,
      raw: true
    });
    const hmacKey = await argon2.hash(passcode + 'hmac', {
      salt: systemKeyBuffer,
      type: argon2.argon2id,
      memoryCost: 65536,
      timeCost: 3,
      parallelism: 1,
      hashLength: 32,
      raw: true
    });

    const computedHmac = crypto.createHmac('sha256', hmacKey)
      .update(encryptedBackup.iv + encryptedBackup.data)
      .digest('hex');
    if (computedHmac !== encryptedBackup.hmac) {
      backupLog.push('[ERROR] HMAC verification failed - data may have been tampered with');
      throw new Error('HMAC verification failed - data may have been tampered with');
    }

    const decipher = crypto.createDecipheriv('aes-256-cbc', encryptionKey, iv);
    let decrypted = decipher.update(encryptedBackup.data, 'hex', 'utf8');
    decrypted += decipher.final('utf8');
    const backupData = JSON.parse(decrypted);

    // Filter vaults to restore based on selected IDs
    const selectedVaultIds = JSON.parse(selectedVaults);
    const vaultsToRestore = backupData.vaults.filter(vault => selectedVaultIds.includes(vault.id));

    const restoreResults = [];
    const totalVaults = vaultsToRestore.length;
    let processedVaults = 0;

    const limit = pLimit(VAULT_CONCURRENCY_LIMIT);
    const vaultPromises = vaultsToRestore.map(vault =>
      limit(async () => {
        console.log(`Restoring vault "${vault.name}"...`);
        backupLog.push(`[INFO] Restoring vault "${vault.name}"`);
        const newVaultName = `${vault.name} (Restored)`;
        const env = { ...process.env, OP_SERVICE_ACCOUNT_TOKEN: serviceToken };
        let newVaultId;

        // Create a new vault for restored items
        try {
          const createVaultCommand = `op vault create "${newVaultName}" --format json`;
          const newVaultOutput = execSync(createVaultCommand, { env, encoding: 'utf8' });
          const newVault = JSON.parse(newVaultOutput);
          newVaultId = newVault.id;
          backupLog.push(`[INFO] Created new vault "${newVaultName}" (ID: ${newVaultId})`);
        } catch (error) {
          backupLog.push(`[ERROR] Failed to create vault "${newVaultName}": ${error.message}`);
          throw new Error(`Failed to create vault "${newVaultName}": ${error.message}`);
        }

        // Restore each item in the vault
        const itemResults = [];
        for (const item of vault.items) {
          try {
            await sdkInstance.createItem(newVaultId, item);
            itemResults.push({ id: item.id, title: item.title, success: true });
            console.log(`Restored item "${item.title}" in vault "${newVaultName}"`);
            backupLog.push(`[INFO] Restored item "${item.title}" in vault "${newVaultName}"`);
          } catch (error) {
            console.error(`Failed to restore item "${item.title}" in vault "${newVaultName}": ${error.message}`);
            backupLog.push(`[ERROR] Failed to restore item "${item.title}" in vault "${newVaultName}": ${error.message}`);
            itemResults.push({ id: item.id, title: item.title, success: false, error: error.message });
          }
        }

        processedVaults++;
        const progress = (processedVaults / totalVaults) * 100;
        const failedItems = itemResults.filter(r => !r.success);

        return {
          vaultId: vault.id,
          vaultName: vault.name,
          success: failedItems.length === 0,
          message: failedItems.length > 0
            ? `Vault "${vault.name}" restored with ${failedItems.length} item failures`
            : `Vault "${vault.name}" restored successfully`,
          items: itemResults,
          progress: progress
        };
      })
    );

    const results = await Promise.all(vaultPromises);
    restoreResults.push(...results);

    const failedVaults = restoreResults.filter(r => !r.success);
    backupLog.push(`[INFO] Restore completed with ${failedVaults.length} vault failures out of ${totalVaults} vaults`);
    res.json({
      success: failedVaults.length === 0,
      message: failedVaults.length > 0
        ? `Restore completed with ${failedVaults.length} vault failures`
        : `Restore completed successfully`,
      results: restoreResults
    });

    fs.unlinkSync(backupFile.path);
  } catch (error) {
    console.error('Error restoring vaults:', error.message);
    backupLog.push(`[ERROR] Error restoring vaults: ${error.message}`);
    fs.unlinkSync(backupFile.path);
    res.status(500).json({ success: false, message: error.message });
  }
});

// Custom class to handle 1Password SDK interactions
class OnePasswordSDK {
  constructor(token) {
    this.token = token;
    this.client = null;
  }

  // Initialize the SDK client with the service token
  async initializeClient() {
    if (!this.token) {
      backupLog.push('[ERROR] Service account token is required');
      throw new Error('Service account token is required.');
    }
    this.client = await sdk.createClient({
      auth: this.token,
      integrationName: "1Password Backup Tool",
      integrationVersion: "1.0.0",
    });
    backupLog.push('[INFO] 1Password SDK client initialized');
  }

  // List all vaults available to the service account
  async listVaults() {
    if (!this.client) await this.initializeClient();
    try {
      const vaults = await this.client.vaults.list();
      const vaultList = vaults.map(vault => ({ id: vault.id, name: vault.title }));
      backupLog.push(`[INFO] Listed ${vaultList.length} vaults`);
      return vaultList;
    } catch (error) {
      backupLog.push(`[ERROR] Failed to list vaults: ${error.message}`);
      throw new Error(`Failed to list vaults: ${error.message}`);
    }
  }

  // Count active items in a vault, logging archived items if any
  async getVaultItemCount(vaultId, vaultName = 'Unknown') {
    try {
      if (!this.client) await this.initializeClient();
      vaultLogs[vaultId] = vaultLogs[vaultId] || [];
      // Fetch only active items for the count
      const activeItems = await this.client.items.list(vaultId);
      const activeCount = activeItems.length;
      // Check for archived items and log them (not included in backup)
      const archivedItems = await this.client.items.list(vaultId, {
        type: "ByState",
        content: { active: false, archived: true }
      });
      const archivedCount = archivedItems.length;
      if (archivedCount > 0) {
        const logMessage = `[INFO] Vault ${vaultId} (${vaultName}): Contains ${archivedCount} archived items`;
        console.log(logMessage);
        backupLog.push(logMessage);
        vaultLogs[vaultId].push(logMessage);
      }
      return activeCount;
    } catch (error) {
      console.error(`Error fetching item count for vault ${vaultId}: ${error.message}`);
      backupLog.push(`[ERROR] Vault ${vaultId} (${vaultName}): Failed to fetch item count - ${error.message}`);
      vaultLogs[vaultId].push(`[ERROR] Failed to fetch item count: ${error.message}`);
      return 0;
    }
  }

  // Fetch active items in a vault, including files and documents
  async listVaultItems(vaultId) {
    if (!this.client) await this.initializeClient();
    try {
      console.log(`Listing items for vault ${vaultId}`);
      backupLog.push(`[INFO] Listing items for vault ${vaultId}`);
      vaultLogs[vaultId] = vaultLogs[vaultId] || [];
      vaultLogs[vaultId].push(`[INFO] Listing items`);
      // Use list() to get only active items, excluding archived ones
      const itemOverviews = await this.client.items.list(vaultId);
      const itemSummaries = itemOverviews.map(item => ({
        id: item.id,
        title: item.title,
        category: item.category
      }));

      // Fetch full details for each item with concurrency control
      const limit = pLimit(ITEM_CONCURRENCY_LIMIT);
      const itemPromises = itemSummaries.map(summary =>
        limit(async () => {
          const fullItem = await this.client.items.get(vaultId, summary.id);
          const websites = fullItem.urls || fullItem.websites || [];
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
          // Include any additional file attachments
          if (fullItem.files && fullItem.files.length > 0) {
            const filePromises = fullItem.files.map(file =>
              this.client.items.files.read(vaultId, fullItem.id, file.attributes)
                .then(content => {
                  const uint8Content = content instanceof Uint8Array ? content : new Uint8Array(content);
                  console.log(`Fetched file "${file.attributes.name}" for "${fullItem.title}", size: ${uint8Content.length}`);
                  backupLog.push(`[INFO] Fetched file "${file.attributes.name}" for "${fullItem.title}", size: ${uint8Content.length}`);
                  return {
                    name: file.attributes.name,
                    content: Buffer.from(uint8Content).toString('base64')
                  };
                })
            );
            itemData.files = await Promise.all(filePromises);
          }
          // Include primary document content for Document items
          if (fullItem.category === 'Document' && fullItem.document) {
            const documentContent = await this.client.items.files.read(vaultId, fullItem.id, fullItem.document);
            const uint8Content = documentContent instanceof Uint8Array ? documentContent : new Uint8Array(documentContent);
            console.log(`Fetched document "${fullItem.document.name}" for "${fullItem.title}", size: ${uint8Content.length}`);
            backupLog.push(`[INFO] Fetched document "${fullItem.document.name}" for "${fullItem.title}", size: ${uint8Content.length}`);
            itemData.document = {
              name: fullItem.document.name,
              content: Buffer.from(uint8Content).toString('base64')
            };
          }
          return itemData;
        })
      );
      const items = await Promise.all(itemPromises);
      console.log(`Listed ${items.length} items for vault ${vaultId}`);
      backupLog.push(`[INFO] Listed ${items.length} items for vault ${vaultId}`);
      vaultLogs[vaultId].push(`[INFO] Listed ${items.length} items`);
      return items;
    } catch (error) {
      console.error(`Failed to list items for vault ${vaultId}: ${error.message}`);
      backupLog.push(`[ERROR] Failed to list items for vault ${vaultId}: ${error.message}`);
      vaultLogs[vaultId].push(`[ERROR] Failed to list items: ${error.message}`);
      throw new Error(`Failed to list items for vault ${vaultId}: ${error.message}`);
    }
  }

  // Create an item in a vault, handling Documents and additional files
  async createItem(vaultId, item) {
    if (!this.client) await this.initializeClient();

    let createdItem;
    try {
      if (item.category === 'Document' && item.document) {
        // Handle Document items with primary document content
        if (!item.document.content) throw new Error('Document content is missing');
        const docBuffer = Buffer.from(item.document.content, 'base64');
        const docContent = new Uint8Array(docBuffer.buffer, docBuffer.byteOffset, docBuffer.byteLength);
        console.log(`Creating Document "${item.title}" with file "${item.document.name}", size: ${docContent.length}`);
        backupLog.push(`[INFO] Creating Document "${item.title}" with file "${item.document.name}", size: ${docContent.length}`);

        const newItem = {
          title: item.title,
          category: sdk.ItemCategory.Document,
          vaultId: vaultId,
          document: {
            name: item.document.name,
            content: docContent,
            contentType: 'application/octet-stream'
          }
        };
        createdItem = await this.client.items.create(newItem);
        console.log(`Document "${item.title}" created with ID: ${createdItem.id}`);
        backupLog.push(`[INFO] Document "${item.title}" created with ID: ${createdItem.id}`);

        // Attach any additional files for Document items (e.g., for "DeleteVaults")
        if (item.files && item.files.length > 0) {
          console.log(`Attaching ${item.files.length} additional files to Document "${item.title}"...`);
          backupLog.push(`[INFO] Attaching ${item.files.length} additional files to Document "${item.title}"`);
          for (const file of item.files) {
            if (!file.content) {
              console.error(`Skipping file "${file.name}" for "${item.title}": content is missing`);
              backupLog.push(`[ERROR] Skipping file "${file.name}" for "${item.title}": content is missing`);
              continue;
            }
            const fileBuffer = Buffer.from(file.content, 'base64');
            const fileContent = new Uint8Array(fileBuffer.buffer, fileBuffer.byteOffset, fileBuffer.byteLength);
            console.log(`Attaching file "${file.name}", size: ${fileContent.length}`);
            backupLog.push(`[INFO] Attaching file "${file.name}", size: ${fileContent.length}`);
            await this.client.items.files.attach(createdItem, {
              name: file.name,
              content: fileContent,
              sectionId: file.sectionId || "restored-section",
              fieldId: file.fieldId || `restored-file-${Date.now()}`,
              contentType: 'application/octet-stream'
            });
            console.log(`File "${file.name}" attached to "${item.title}"`);
            backupLog.push(`[INFO] File "${file.name}" attached to "${item.title}"`);
          }
        }
      } else {
        // Handle non-Document items (Logins, Secure Notes, etc.)
        const sectionIdsFromFields = new Set();
        if (item.fields) {
          item.fields.forEach(field => {
            if (field.sectionId) sectionIdsFromFields.add(field.sectionId);
          });
        }

        const sections = item.sections ? [...item.sections] : [];
        sectionIdsFromFields.forEach(sectionId => {
          if (!sections.some(section => section.id === sectionId)) {
            sections.push({ id: sectionId, title: sectionId || 'Restored Section' });
          }
        });

        const newItem = {
          title: item.title,
          category: item.category || sdk.ItemCategory.Login,
          vaultId: vaultId,
          fields: item.fields || [],
          sections: sections,
          tags: item.tags || [],
          websites: item.websites || [],
          notes: item.notes || ""
        };
        console.log(`Creating item "${item.title}"...`);
        backupLog.push(`[INFO] Creating item "${item.title}"`);
        createdItem = await this.client.items.create(newItem);
        console.log(`Item "${item.title}" created with ID: ${createdItem.id}`);
        backupLog.push(`[INFO] Item "${item.title}" created with ID: ${createdItem.id}`);

        // Attach any files for non-Document items
        if (item.files && item.files.length > 0) {
          console.log(`Attaching ${item.files.length} files to "${item.title}"...`);
          backupLog.push(`[INFO] Attaching ${item.files.length} files to "${item.title}"`);
          for (const file of item.files) {
            if (!file.content) {
              console.error(`Skipping file "${file.name}" for "${item.title}": content is missing`);
              backupLog.push(`[ERROR] Skipping file "${file.name}" for "${item.title}": content is missing`);
              continue;
            }
            const fileBuffer = Buffer.from(file.content, 'base64');
            const fileContent = new Uint8Array(fileBuffer.buffer, fileBuffer.byteOffset, fileBuffer.byteLength);
            console.log(`Attaching file "${file.name}", size: ${fileContent.length}`);
            backupLog.push(`[INFO] Attaching file "${file.name}", size: ${fileContent.length}`);
            await this.client.items.files.attach(createdItem, {
              name: file.name,
              content: fileContent,
              sectionId: file.sectionId || "restored-section",
              fieldId: file.fieldId || `restored-file-${Date.now()}`,
              contentType: 'application/octet-stream'
            });
            console.log(`File "${file.name}" attached to "${item.title}"`);
            backupLog.push(`[INFO] File "${file.name}" attached to "${item.title}"`);
          }
        }
      }
    } catch (error) {
      console.error(`Item creation failed for "${item.title}": ${error.message}`);
      backupLog.push(`[ERROR] Item creation failed for "${item.title}": ${error.message}`);
      throw new Error(`Item creation failed for "${item.title}": ${error.message}`);
    }
    return createdItem;
  }
}

// Start the HTTPS server with a self-signed certificate
const PORT = 3002;
const attrs = [{ name: 'commonName', value: 'localhost' }];
const opts = { keySize: 2048, algorithm: 'sha256', days: 365 };

selfsigned.generate(attrs, opts, (err, pems) => {
  if (err) {
    console.error('Error generating cert:', err.message);
    backupLog.push(`[ERROR] Error generating cert: ${err.message}`);
    return;
  }

  const options = {
    key: pems.private,
    cert: pems.cert,
  };

  https.createServer(options, app).listen(PORT, () => {
    console.log(`Server running on https://localhost:${PORT}`);
    backupLog.push(`[INFO] Server running on https://localhost:${PORT}`);
  });
});