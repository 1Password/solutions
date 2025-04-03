import { InnerClient } from "./core.js";
import { Item, ItemShareAccountPolicy, ItemShareParams, ValidRecipient } from "./types.js";
export interface ItemsSharesApi {
    /**
     * Get the item sharing policy of your account.
     */
    getAccountPolicy(vaultId: string, itemId: string): Promise<ItemShareAccountPolicy>;
    /**
     * Validate the recipients of an item sharing link.
     */
    validateRecipients(policy: ItemShareAccountPolicy, recipients: string[]): Promise<ValidRecipient[]>;
    /**
     * Create a new item sharing link.
     */
    create(item: Item, policy: ItemShareAccountPolicy, params: ItemShareParams): Promise<string>;
}
export declare class ItemsShares implements ItemsSharesApi {
    #private;
    constructor(inner: InnerClient);
    /**
     * Get the item sharing policy of your account.
     */
    getAccountPolicy(vaultId: string, itemId: string): Promise<ItemShareAccountPolicy>;
    /**
     * Validate the recipients of an item sharing link.
     */
    validateRecipients(policy: ItemShareAccountPolicy, recipients: string[]): Promise<ValidRecipient[]>;
    /**
     * Create a new item sharing link.
     */
    create(item: Item, policy: ItemShareAccountPolicy, params: ItemShareParams): Promise<string>;
}
