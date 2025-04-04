import sdk from "@1password/sdk";
import express from "express";
import bodyParser from "body-parser";

const app = express();
app.set("view engine", "ejs");
app.use(bodyParser.urlencoded({ extended: true }));
app.use(bodyParser.json());
app.use(express.static("public"));

const vaultId = process.env.OP_VAULT;
const port = 3000;

const opClientConfig = {
  auth: process.env.OP_SERVICE_ACCOUNT_TOKEN,
  integrationName: "Basic JS Example",
  integrationVersion: "v1.0.0",
};

const client = await sdk.createClient(opClientConfig);

const createItem = async (vaultID, data) => {
  console.log("Creating item with");

  const item = await client.items.create({
    title: data.deviceName,
    category: sdk.ItemCategory.Login,
    vaultId: vaultID,
    fields: [
      {
        id: "username",
        title: "username",
        fieldType: sdk.ItemFieldType.Text,
        value: data.adminUsername,
      },
      {
        id: "password",
        title: "password",
        fieldType: sdk.ItemFieldType.Concealed,
        value: data.password,
      },
      {
        id: "deviceName",
        title: "Device Name",
        sectionId: "deviceDetails",
        fieldType: sdk.ItemFieldType.Text,
        value: data.deviceName,
      },
      {
        id: "deviceModel",
        title: "Model Number",
        sectionId: "deviceDetails",
        fieldType: sdk.ItemFieldType.Text,
        value: data.deviceModel,
      },
      {
        id: "deviceSerial",
        title: "Serial Number",
        sectionId: "deviceDetails",
        fieldType: sdk.ItemFieldType.Text,
        value: data.deviceSerial,
      },
      {
        id: "adminUsername",
        title: "Device Admin Username",
        sectionId: "deviceDetails",
        fieldType: sdk.ItemFieldType.Text,
        value: data.adminUsername,
      },
    ],
    sections: [
      {
        id: "deviceDetails",
        title: "Device Details",
      },
    ],
    tags: [],
  });
  return item;
};

const generatePassword = async () => {
  return sdk.Secrets.generatePassword({
    type: "Random",
    parameters: {
      includeDigits: true,
      includeSymbols: true,
      length: 32,
    },
  });
};

const updateItem = async (updatedItemData, itemID) => {
  console.log(`Updating item with ID: ${itemID}`);
  const oldItem = await getOneItem(itemID);

  const newItem = {
    ...oldItem,
    title: updatedItemData.deviceName,
    fields: oldItem.fields.map((field) => {
      if (field.id === "password") {
        if (updatedItemData.password !== "") {
          return { ...field, value: updatedItemData.password };
        }
        return field;
      } else if (field.id === "adminUsername" || field.id === "username") {
        return {
          ...field,
          value: updatedItemData.adminUsername,
        };
      } else if (updatedItemData[field.id]) {
        return { ...field, value: updatedItemData[field.id] };
      }
      return field;
    }),
  };
  const updatedItem = await client.items.put(newItem);
  return updatedItem;
};

const getAllItems = async () => {
  const itemList = await client.items.listAll(vaultId);

  const itemPromises = itemList.elements.map(async (item) => {
    return await client.items.get(vaultId, item.id);
  });

  const items = await Promise.all(itemPromises);
  return items;
};

const getOneItem = async (itemId) => {
  const foundItem = await client.items.get(vaultId, itemId);
  return foundItem;
};

const deleteItem = async (itemId) => {
  console.log(`Attempting to delete item with ID: ${itemId}`);
  await client.items.delete(vaultId, itemId);
};

app.get("/", (req, res) => {
  res.render("index", {
    title: "Knox IT Resource Manager",
    currentPage: "home",
    item: null,
  });
});

app.get("/generate-password", async (req, res) => {
  try {
    const generatedPassword = await generatePassword();
    res.json({ generatedPassword: generatedPassword.password });
  } catch (error) {}
});

app.get("/items", async (req, res) => {
  try {
    const items = await getAllItems();
    res.render("items", {
      items,
      currentPage: "item",
      title: "Inventory List",
    });
  } catch (error) {
    console.error("Error fetching items:", error);
    res.status(500).send("Oops, something went wrong getting items");
  }
});

app.get("/items/:item", async (req, res) => {
  try {
    const item = await client.items.get(vaultId, req.params.item);
    res.render("item", { item, currentPage: "item", title: "Item Details" });
  } catch (error) {
    console.error("Error fetching item:", error);
    res.status(404).send(`Unable to find item with UUID: ${req.params.item}`);
  }
});

app.get("/edit/:item", async (req, res) => {
  try {
    const itemId = req.params.item;
    const item = await getOneItem(itemId);

    res.render("index", { item, currentPage: "item", title: "Edit Item" });
  } catch (error) {
    console.error("Error fetching item:", error);
    res.status(500).send("There was an error");
  }
});

app.post("/submit", async (req, res) => {
  const {
    itemId,
    deviceName,
    deviceModel,
    deviceSerial,
    adminUsername,
    password,
  } = req.body;
  const updatedItemData = {
    deviceName,
    deviceModel,
    deviceSerial,
    adminUsername,
    password,
  };
  try {
    if (itemId) {
      const updatedItem = await updateItem(updatedItemData, itemId);
      res.redirect(`items/${updatedItem.id}`);
    } else {
      const item = await createItem(vaultId, updatedItemData);
      res.redirect(`items/${item.id}`);
    }
  } catch (error) {
    console.error("Error submitting item:", error);
    res.status(500).send("There was an error");
  }
});

app.post("/delete", async (req, res) => {
  try {
    const { itemId } = req.body;
    await deleteItem(itemId);
    res.redirect("/items");
  } catch (error) {
    console.error("Error deleting item:", error);
    res.status(500).send("There was an error");
  }
});

app.listen(port, () => {
  console.log(`Listening on port ${port}`);
});
