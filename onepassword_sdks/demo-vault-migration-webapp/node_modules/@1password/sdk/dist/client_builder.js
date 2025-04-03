"use strict";
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.createClientWithCore = void 0;
const configuration_js_1 = require("./configuration.js");
const client_js_1 = require("./client.js");
const finalizationRegistry = new FinalizationRegistry((heldClient) => {
    heldClient.core.releaseClient(heldClient.id);
});
/**
 * Creates a 1Password SDK client with a given core implementation.
 * @returns The authenticated 1Password SDK client.
 */
const createClientWithCore = (config, core) => __awaiter(void 0, void 0, void 0, function* () {
    const authConfig = (0, configuration_js_1.clientAuthConfig)(config);
    const clientId = yield core.initClient(authConfig);
    const inner = {
        id: parseInt(clientId, 10),
        core,
    };
    const client = new client_js_1.Client(inner);
    // Cleans up associated memory from core when client instance goes out of scope.
    finalizationRegistry.register(client, inner);
    return client;
});
exports.createClientWithCore = createClientWithCore;
