import { Core } from "./core.js";
import { ClientConfiguration } from "./configuration.js";
import { Client } from "./client.js";
/**
 * Creates a 1Password SDK client with a given core implementation.
 * @returns The authenticated 1Password SDK client.
 */
export declare const createClientWithCore: (config: ClientConfiguration, core: Core) => Promise<Client>;
