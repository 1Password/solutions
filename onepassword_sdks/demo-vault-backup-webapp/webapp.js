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

const upload = multer({ dest: 'uploads/', limits: { fileSize: 500 * 1024 * 1024 } }); // Add file size limit (500MB)

// Dynamically import p-limit for concurrency control
let pLimit;
async function loadPLimit() {
  try {
    const { default: pLimitModule } = await import('p-limit'); // Use named import for ES module
    pLimit = pLimitModule;
  } catch (error) {
    console.error('Failed to load p-limit, disabling concurrency limits:', error);
    pLimit = () => (fn) => fn(); // Simplified fallback
  }
}

// Start the app once p-limit is loaded
loadPLimit().then(() => {
  const VAULT_CONCURRENCY_LIMIT = 2;
  const ITEM_CONCURRENCY_LIMIT = 1;

  const app = express();

  app.set('views', path.join(__dirname, 'views'));
  app.set('view engine', 'ejs');

  app.use(express.static(path.join(__dirname, 'public'))); // Specify full path for clarity
  app.use(bodyParser.urlencoded({ extended: true }));
  app.use(bodyParser.json());
  app.use(session({
    secret: crypto.randomBytes(32).toString('hex'), // Generate random secret
    resave: false,
    saveUninitialized: false,
    cookie: { secure: true, httpOnly: true, sameSite: 'strict', maxAge: 24 * 60 * 60 * 1000 } // Enforce secure cookies
  }));

  // Middleware to ensure HTTPS
  app.use((req, res, next) => {
    if (!req.secure) {
      return res.redirect(`https://${req.headers.host}${req.url}`);
    }
    next();
  });

  app.get('/', (req, res) => {
    res.render('welcome', { currentPage: 'welcome' });
  });

  app.get('/backup', (req, res) => {
    res.render('backup', { error: null, currentPage: 'backup' });
  });

  app.get('/restore', (req, res) => {
    res.render('restore', { error: null, currentPage: 'restore' });
  });

  app.post('/backup/list-vaults', async (req, res) => {
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
      res.status(500).json({ success: false, error: 'Failed to list vaults' });
    }
  });

  app.post('/backup/backup-vaults', async (req, res) => {
    const { serviceToken, vaults, passcode } = req.body;
    if (!serviceToken || !vaults || !passcode) {
      return res.status(400).json({ success: false, message: 'Service token, vaults, and passcode are required' });
    }
    if (passcode.length < 12) { // Increase minimum length for security
      return res.status(400).json({ success: false, message: 'Passcode must be at least 12 characters long' });
    }

    try {
      const sdkInstance = new OnePasswordSDK(serviceToken);
      await sdkInstance.initializeClient();

      const systemKey = crypto.randomBytes(32); // Increase to 32 bytes for stronger key
      const encryptionKey = await argon2.hash(passcode, {
        salt: systemKey,
        type: argon2.argon2id,
        memoryCost: 19456, // Align with OWASP recommendations
        timeCost: 2,
        parallelism: 1,
        hashLength: 32,
        raw: true
      });
      const hmacKey = await argon2.hash(passcode + 'hmac', {
        salt: systemKey,
        type: argon2.argon2id,
        memoryCost: 19456,
        timeCost: 2,
        parallelism: 1,
        hashLength: 32,
        raw: true
      });
      const iv = crypto.randomBytes(12); // Use 12 bytes for GCM

      const vaultsToBackup = vaults.map(v => ({ id: v.vaultId, name: v.vaultName }));
      const backupData = { vaults: [], systemKey: systemKey.toString('hex') };

      const limit = pLimit(VAULT_CONCURRENCY_LIMIT);
      const vaultPromises = vaultsToBackup.map(vault =>
        limit(async () => {
          console.log(`Backing up vault "${vault.name}" (ID: ${vault.id})...`);
          const items = await sdkInstance.listVaultItems(vault.id);
          return { id: vault.id, name: vault.name, items };
        })
      );

      backupData.vaults = await Promise.all(vaultPromises);

      const cipher = crypto.createCipheriv('aes-256-gcm', encryptionKey, iv); // Use GCM for better security
      let encrypted = cipher.update(JSON.stringify(backupData), 'utf8', 'hex');
      encrypted += cipher.final('hex');
      const authTag = cipher.getAuthTag().toString('hex'); // Store auth tag for GCM
      const hmac = crypto.createHmac('sha256', hmacKey)
        .update(iv.toString('hex') + encrypted + authTag)
        .digest('hex');
      const encryptedBackup = { iv: iv.toString('hex'), data: encrypted, hmac, authTag };

      const backupFilePath = path.join(__dirname, 'public', `backup-${Date.now()}.1pbackup`); // Unique filename
      fs.writeFileSync(backupFilePath, JSON.stringify(encryptedBackup, null, 2));

      res.json({ success: true, systemKey: systemKey.toString('hex'), passcode, filePath: `/backup-${Date.now()}.1pbackup` });
    } catch (error) {
      console.error('Error backing up vaults:', error);
      res.status(500).json({ success: false, message: 'Failed to backup vaults' });
    }
  });

  app.post('/backup/save-keys', async (req, res) => {
    const { serviceToken, systemKey, passcode } = req.body;
    if (!serviceToken || !systemKey || !passcode) {
      return res.status(400).json({ success: false, message: 'Service token, system key, and passcode are required' });
    }

    try {
      const sdkInstance = new OnePasswordSDK(serviceToken);
      await sdkInstance.initializeClient();

      const vaultName = "Backup Keys";
      let vaultId;
      try {
        const vaults = await sdkInstance.listVaults();
        const existingVault = vaults.find(v => v.name === vaultName);
        if (existingVault) {
          vaultId = existingVault.id;
        } else {
          const newVault = await sdkInstance.client.vaults.create({ title: vaultName });
          vaultId = newVault.id;
        }
      } catch (error) {
        return res.status(403).json({ success: false, message: 'Failed to create or access vault' });
      }

      const item = {
        title: `Backup Keys - ${new Date().toISOString().split('T')[0]}`,
        category: 'SECURE_NOTE',
        vaultId: vaultId,
        fields: [
          { id: 'passcode', label: 'Passcode', type: 'CONCEALED', value: passcode },
          { id: 'systemKey', label: 'System Key', type: 'STRING', value: systemKey }
        ],
        notesPlain: 'Generated keys for 1Password backup'
      };
      await sdkInstance.createItem(vaultId, item);

      res.json({ success: true, message: `Keys saved to vault "${vaultName}"` });
    } catch (error) {
      console.error('Error saving keys to 1Password:', error);
      res.status(500).json({ success: false, message: 'Failed to save keys' });
    }
  });

  app.post('/restore/list-vaults', upload.single('backupFile'), async (req, res) => {
    const { serviceToken, passcode, systemKey } = req.body;
    const backupFile = req.file;

    if (!serviceToken || !passcode || !systemKey || !backupFile) {
      return res.status(400).json({ success: false, message: 'Service token, passcode, system key, and backup file are required' });
    }

    try {
      const sdkInstance = new OnePasswordSDK(serviceToken);
      await sdkInstance.initializeClient();

      const encryptedBackup = JSON.parse(fs.readFileSync(backupFile.path, 'utf8'));
      const iv = Buffer.from(encryptedBackup.iv, 'hex');
      const systemKeyBuffer = Buffer.from(systemKey, 'hex');
      const encryptionKey = await argon2.hash(passcode, {
        salt: systemKeyBuffer,
        type: argon2.argon2id,
        memoryCost: 19456,
        timeCost: 2,
        parallelism: 1,
        hashLength: 32,
        raw: true
      });
      const hmacKey = await argon2.hash(passcode + 'hmac', {
        salt: systemKeyBuffer,
        type: argon2.argon2id,
        memoryCost: 19456,
        timeCost: 2,
        parallelism: 1,
        hashLength: 32,
        raw: true
      });

      const computedHmac = crypto.createHmac('sha256', hmacKey)
        .update(encryptedBackup.iv + encryptedBackup.data + encryptedBackup.authTag)
        .digest('hex');
      if (computedHmac !== encryptedBackup.hmac) {
        throw new Error('HMAC verification failed - data may have been tampered with');
      }

      const decipher = crypto.createDecipheriv('aes-256-gcm', encryptionKey, iv);
      decipher.setAuthTag(Buffer.from(encryptedBackup.authTag, 'hex')); // Set auth tag for GCM
      let decrypted = decipher.update(encryptedBackup.data, 'hex', 'utf8');
      decrypted += decipher.final('utf8');
      const backupData = JSON.parse(decrypted);

      const vaults = backupData.vaults.map(vault => ({
        id: vault.id,
        name: vault.name,
        itemCount: vault.items.length
      }));

      fs.unlinkSync(backupFile.path); // Clean up temp file
      res.json({ success: true, vaults });
    } catch (error) {
      console.error('Error listing vaults from backup:', error);
      if (fs.existsSync(backupFile.path)) fs.unlinkSync(backupFile.path); // Clean up even on error
      res.status(500).json({ success: false, message: 'Failed to list vaults from backup' });
    }
  });

  app.post('/restore/restore-vaults', upload.single('backupFile'), async (req, res) => {
    const { serviceToken, passcode, systemKey, selectedVaults } = req.body;
    const backupFile = req.file;

    if (!serviceToken || !passcode || !systemKey || !backupFile || !selectedVaults) {
      return res.status(400).json({ success: false, message: 'Service token, passcode, system key, backup file, and selected vaults are required' });
    }

    try {
      const sdkInstance = new OnePasswordSDK(serviceToken);
      await sdkInstance.initializeClient();

      const encryptedBackup = JSON.parse(fs.readFileSync(backupFile.path, 'utf8'));
      const iv = Buffer.from(encryptedBackup.iv, 'hex');
      const systemKeyBuffer = Buffer.from(systemKey, 'hex');
      const encryptionKey = await argon2.hash(passcode, {
        salt: systemKeyBuffer,
        type: argon2.argon2id,
        memoryCost: 19456,
        timeCost: 2,
        parallelism: 1,
        hashLength: 32,
        raw: true
      });
      const hmacKey = await argon2.hash(passcode + 'hmac', {
        salt: systemKeyBuffer,
        type: argon2.argon2id,
        memoryCost: 19456,
        timeCost: 2,
        parallelism: 1,
        hashLength: 32,
        raw: true
      });

      const computedHmac = crypto.createHmac('sha256', hmacKey)
        .update(encryptedBackup.iv + encryptedBackup.data + encryptedBackup.authTag)
        .digest('hex');
      if (computedHmac !== encryptedBackup.hmac) {
        throw new Error('HMAC verification failed - data may have been tampered with');
      }

      const decipher = crypto.createDecipheriv('aes-256-gcm', encryptionKey, iv);
      decipher.setAuthTag(Buffer.from(encryptedBackup.authTag, 'hex')); // Set auth tag for GCM
      let decrypted = decipher.update(encryptedBackup.data, 'hex', 'utf8');
      decrypted += decipher.final('utf8');
      const backupData = JSON.parse(decrypted);

      const selectedVaultIds = JSON.parse(selectedVaults);
      const vaultsToRestore = backupData.vaults.filter(vault => selectedVaultIds.includes(vault.id));

      const restoreResults = [];
      const totalVaults = vaultsToRestore.length;
      let processedVaults = 0;

      const limit = pLimit(VAULT_CONCURRENCY_LIMIT);
      const vaultPromises = vaultsToRestore.map(vault =>
        limit(async () => {
          console.log(`Restoring vault "${vault.name}"...`);
          const newVaultName = `${vault.name} (Restored)`;
          let newVaultId;

          try {
            const vaults = await sdkInstance.listVaults();
            const existingVault = vaults.find(v => v.name === newVaultName);
            if (existingVault) {
              newVaultId = existingVault.id;
            } else {
              const newVault = await sdkInstance.client.vaults.create({ title: newVaultName });
              newVaultId = newVault.id;
            }
          } catch (error) {
            throw new Error(`Failed to create vault "${newVaultName}": ${error.message}`);
          }

          const itemResults = [];
          for (const item of vault.items) {
            try {
              await sdkInstance.createItem(newVaultId, item);
              itemResults.push({ id: item.id, title: item.title, success: true });
              console.log(`Restored item "${item.title}" in vault "${newVaultName}"`);
            } catch (error) {
              console.error(`Failed to restore item "${item.title}" in vault "${newVaultName}": ${error.message}`);
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
      res.json({
        success: failedVaults.length === 0,
        message: failedVaults.length > 0
          ? `Restore completed with ${failedVaults.length} vault failures`
          : `Restore completed successfully`,
        results: restoreResults
      });

      fs.unlinkSync(backupFile.path);
    } catch (error) {
      console.error('Error restoring vaults:', error);
      if (fs.existsSync(backupFile.path)) fs.unlinkSync(backupFile.path);
      res.status(500).json({ success: false, message: 'Failed to restore vaults' });
    }
  });

  class OnePasswordSDK {
    constructor(token) {
      this.token = token;
      this.client = null;
    }

    async initializeClient() {
      if (!this.token) throw new Error('Service account token is required.');
      this.client = await sdk.createClient({
        auth: this.token,
        integrationName: "1Password Backup Tool",
        integrationVersion: "1.0.0",
      });
    }

    async listVaults() {
      if (!this.client) await this.initializeClient();
      const vaultIterator = await this.client.vaults.listAll();
      const vaults = [];
      for await (const vault of vaultIterator) {
        vaults.push({ id: vault.id, name: vault.title });
      }
      return vaults;
    }

    async listVaultItems(vaultId) {
      if (!this.client) await this.initializeClient();
      const itemsIterator = await this.client.items.listAll(vaultId);
      const itemSummaries = [];
      for await (const item of itemsIterator) {
        itemSummaries.push({ id: item.id, title: item.title, category: item.category });
      }

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
          if (fullItem.files && fullItem.files.length > 0) {
            const filePromises = fullItem.files.map(file =>
              this.client.items.files.read(vaultId, fullItem.id, file.attributes)
                .then(content => {
                  const uint8Content = content instanceof Uint8Array ? content : new Uint8Array(content);
                  console.log(`Fetched file "${file.attributes.name}" for "${fullItem.title}", size: ${uint8Content.length}`);
                  return {
                    name: file.attributes.name,
                    content: Buffer.from(uint8Content).toString('base64')
                  };
                })
            );
            itemData.files = await Promise.all(filePromises);
          }
          if (fullItem.category === 'DOCUMENT' && fullItem.document) {
            const documentContent = await this.client.items.files.read(vaultId, fullItem.id, fullItem.document);
            const uint8Content = documentContent instanceof Uint8Array ? documentContent : new Uint8Array(documentContent);
            console.log(`Fetched document "${fullItem.document.name}" for "${fullItem.title}", size: ${uint8Content.length}`);
            itemData.document = {
              name: fullItem.document.name,
              content: Buffer.from(uint8Content).toString('base64')
            };
          }
          return itemData;
        })
      );
      return await Promise.all(itemPromises);
    }

    async createItem(vaultId, item) {
      if (!this.client) await this.initializeClient();

      let createdItem;
      try {
        if (item.category === 'DOCUMENT' && item.document) {
          if (!item.document.content) throw new Error('Document content is missing');
          const docBuffer = Buffer.from(item.document.content, 'base64');
          const docContent = new Uint8Array(docBuffer.buffer, docBuffer.byteOffset, docBuffer.byteLength);
          console.log(`Creating Document "${item.title}" with file "${item.document.name}", size: ${docContent.length}`);

          const newItem = {
            title: item.title,
            category: 'DOCUMENT',
            vaultId: vaultId,
            document: {
              name: item.document.name,
              content: docContent,
              contentType: 'application/octet-stream'
            }
          };
          createdItem = await this.client.items.create(newItem);
          console.log(`Document "${item.title}" created with ID: ${createdItem.id}`);
        } else {
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
            category: item.category || 'LOGIN',
            vaultId: vaultId,
            fields: item.fields || [],
            sections: sections,
            tags: item.tags || [],
            websites: item.websites || [],
            notes: item.notes || ""
          };
          console.log(`Creating item "${item.title}"...`);
          createdItem = await this.client.items.create(newItem);
          console.log(`Item "${item.title}" created with ID: ${createdItem.id}`);

          if (item.files && item.files.length > 0) {
            console.log(`Attaching ${item.files.length} files to "${item.title}"...`);
            for (const file of item.files) {
              if (!file.content) {
                console.error(`Skipping file "${file.name}" for "${item.title}": content is missing`);
                continue;
              }
              const fileBuffer = Buffer.from(file.content, 'base64');
              const fileContent = new Uint8Array(fileBuffer.buffer, fileBuffer.byteOffset, fileBuffer.byteLength);
              console.log(`Attaching file "${file.name}", size: ${fileContent.length}`);
              await this.client.items.files.attach(createdItem, {
                name: file.name,
                content: fileContent,
                sectionId: file.sectionId || "restored-section",
                fieldId: file.fieldId || `restored-file-${Date.now()}`,
                contentType: 'application/octet-stream'
              });
              console.log(`File "${file.name}" attached to "${item.title}"`);
            }
          }
        }
      } catch (error) {
        console.error(`Full error details: ${JSON.stringify(error, null, 2)}`);
        throw new Error(`Item creation failed for "${item.title}": ${error.message}`);
      }
      return createdItem;
    }
  }

  const PORT = 3002;
  const attrs = [{ name: 'commonName', value: 'localhost' }];
  const opts = { keySize: 2048, algorithm: 'sha256', days: 365 };

  selfsigned.generate(attrs, opts, (err, pems) => {
    if (err) {
      console.error('Error generating cert:', err);
      process.exit(1);
    }

    const options = {
      key: pems.private,
      cert: pems.cert,
    };

    https.createServer(options, app).listen(PORT, () => {
      console.log(`Server running on https://localhost:${PORT}`);
    });
  });
});