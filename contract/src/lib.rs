// NOVA contract version 0.1.0
use near_sdk::{env, log, near, AccountId, BorshStorageKey, PanicOnDefault};
use near_sdk::borsh::{BorshDeserialize, BorshSerialize};
use near_sdk::store::{LookupMap, Vector as StoreVec, IterableMap};
use near_sdk::base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine};
use near_sdk::serde::{Deserialize, Serialize};
use schemars::JsonSchema;

// Define the contract structure
#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Contract {
    owner: AccountId,
    groups: LookupMap<String, Group>,
    group_members: LookupMap<String, StoreVec<AccountId>>,
    transactions: IterableMap<String, Transaction>,
}

#[derive(BorshStorageKey, BorshSerialize)]
enum StorageKey {
    Groups,
    GroupMembers,
    Transactions,
}

#[derive(BorshDeserialize, BorshSerialize, Clone)]
pub struct Group {
    owner: AccountId,
    group_key: Option<String>,
}

#[derive(BorshDeserialize, BorshSerialize, Clone, Serialize, Deserialize, JsonSchema)]
#[serde(crate = "near_sdk::serde")]
pub struct Transaction {
    group_id: String,
    user_id: String,
    file_hash: String,
    ipfs_hash: String,
}

// Implement the contract structure
#[near]
impl Contract {
    #[init]
    pub fn new(owner: AccountId) -> Self {
        Self {
            owner,
            groups: LookupMap::new(StorageKey::Groups),
            group_members: LookupMap::new(StorageKey::GroupMembers),
            transactions: IterableMap::new(StorageKey::Transactions),
        }
    }

    #[payable]
    pub fn register_group(&mut self, group_id: String) {
        assert!(!self.groups.contains_key(&group_id), "Group exists");
        let caller = env::predecessor_account_id();
        assert_eq!(caller, self.owner, "Only owner can register");  // Simplify for MVP; add agents later
        let group = Group { 
            owner: caller.clone(), 
            group_key: None 
        };
        self.groups.insert(group_id.clone(), group);
        self.group_members.insert(group_id.clone(), StoreVec::new(StorageKey::GroupMembers));
        log!("Group {} registered by {}", group_id, caller);
    }

    pub fn groups_contains_key(&self, group_id: String) -> bool {
        self.groups.contains_key(&group_id)
    }

    #[payable]
    pub fn add_group_member(&mut self, group_id: String, user_id: AccountId) {
        let group = self.groups.get(&group_id).expect("Group not found");
        let caller = env::predecessor_account_id();
        assert_eq!(caller, group.owner, "Only group owner can add");
        let members = self.group_members.get_mut(&group_id).expect("Group not found");
        assert!(!members.iter().any(|x| *x == user_id), "User already a member");
        members.push(user_id.clone());
        log!("Added {} to group {}", user_id, group_id);
    }

    #[payable]
    pub fn revoke_group_member(&mut self, group_id: String, user_id: AccountId) {
        let group = self.groups.get(&group_id).expect("Group not found");
        let caller = env::predecessor_account_id();
        assert_eq!(caller, group.owner, "Only group owner can revoke");
        let members = self.group_members.get_mut(&group_id).expect("Group not found");
        if let Some(pos) = members.iter().position(|x| x == &user_id) {
            members.swap_remove(pos.try_into().unwrap());
            // Auto-rotate key
            let new_key_bytes: Vec<u8> = env::random_seed()[0..32].to_vec();
            let new_key = BASE64_STANDARD.encode(new_key_bytes);
            let mut group = group.clone();
            group.group_key = Some(new_key);
            self.groups.insert(group_id.clone(), group); // Clone group_id to avoid move
            log!("Revoked {} from group {} and rotated key", user_id, group_id);
        } else {
            env::panic_str("User not a member");
        }
    }

    pub fn is_authorized(&self, group_id: String, user_id: AccountId) -> bool {
        let members = self.group_members.get(&group_id).expect("Group not found");
        members.iter().any(|x| *x == user_id)
    }

    #[payable]
    pub fn store_group_key(&mut self, group_id: String, key: String) {
        let group = self.groups.get(&group_id).expect("Group not found");
        let caller = env::predecessor_account_id();
        assert_eq!(caller, group.owner, "Only group owner can store key");
        let key_bytes = BASE64_STANDARD.decode(&key).expect("Invalid base64 key");
        assert_eq!(key_bytes.len(), 32, "Key must be 32 bytes");
        let mut group = group.clone();
        group.group_key = Some(key);
        self.groups.insert(group_id.clone(), group);
        log!("Key stored for group {}", group_id);
    }

    pub fn get_group_key(&self, group_id: String) -> String {
        let caller = env::predecessor_account_id();
        assert!(self.is_authorized(group_id.clone(), caller), "Unauthorized");
        let group = self.groups.get(&group_id).expect("Group not found");
        group.group_key.clone().expect("No key set")
    }

    #[payable]
    pub fn record_transaction(&mut self, group_id: String, user_id: AccountId, file_hash: String, ipfs_hash: String) -> String {
        assert!(self.groups.contains_key(&group_id), "Group not found");
        assert!(self.is_authorized(group_id.clone(), user_id.clone()), "User not authorized");
        let caller = env::predecessor_account_id();
        assert_eq!(caller, self.owner, "Only owner can record"); // MVP: restrict to owner; expand to agents later
        let trans_id = hex::encode(env::sha256(&format!(
            "{}{}{}{}{}",
            group_id,
            user_id,
            file_hash,
            ipfs_hash,
            env::block_timestamp()
        ).as_bytes()));
        let tx = Transaction {
            group_id,
            user_id: user_id.to_string(),
            file_hash,
            ipfs_hash,
        };
        self.transactions.insert(trans_id.clone(), tx);
        log!("Transaction recorded: {}", trans_id);
        trans_id
    }

    pub fn get_transactions_for_group(&self, group_id: String, user_id: AccountId) -> Vec<Transaction> {
        assert!(self.groups.contains_key(&group_id), "Group not found");
        assert!(self.is_authorized(group_id.clone(), user_id.clone()) || user_id == self.owner, "Unauthorized");
        self.transactions
            .values()
            .filter(|tx| tx.group_id == group_id)
            .cloned()
            .collect()
    }
}

// Inline tests (not compiled into the final contract)
#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::{testing_env, AccountId};

    fn get_context(signer: AccountId) -> VMContextBuilder {
        let mut builder = VMContextBuilder::new();
        builder.signer_account_id(signer.clone());
        builder.predecessor_account_id(signer);
        builder
    }

    #[test]
    fn register_group_works() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner.clone());
        contract.register_group("test_group".to_string());
        assert!(contract.groups.contains_key(&"test_group".to_string()));
    }

    #[test]
    #[should_panic(expected = "Only owner can register")]
    fn register_group_fails_non_owner() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let non_owner: AccountId = "not_owner.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner);
        // Switch context to non_owner
        let context = get_context(non_owner);
        testing_env!(context.build());
        contract.register_group("test_group".to_string());
    }

    #[test]
    fn add_group_member_works() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let member: AccountId = "member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner.clone());
        contract.register_group("test_group".to_string());
        contract.add_group_member("test_group".to_string(), member.clone());
        assert!(contract.is_authorized("test_group".to_string(), member));
    }

    #[test]
    #[should_panic(expected = "Only group owner can add")]
    fn add_group_member_fails_non_owner() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let non_owner: AccountId = "not_owner.testnet".parse().expect("Invalid AccountId");
        let member: AccountId = "member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner);
        contract.register_group("test_group".to_string());
        let context = get_context(non_owner);
        testing_env!(context.build());
        contract.add_group_member("test_group".to_string(), member);
    }

    #[test]
    fn revoke_group_member_works() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let member: AccountId = "member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner.clone());
        contract.register_group("test_group".to_string());
        contract.add_group_member("test_group".to_string(), member.clone());
        contract.revoke_group_member("test_group".to_string(), member.clone());
        assert!(!contract.is_authorized("test_group".to_string(), member));
        assert!(contract.groups.get(&"test_group".to_string()).unwrap().group_key.is_some());
    }

    #[test]
    #[should_panic(expected = "User not a member")]
    fn revoke_group_member_fails_non_member() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let member: AccountId = "member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner);
        contract.register_group("test_group".to_string());
        contract.revoke_group_member("test_group".to_string(), member);
    }

    #[test]
    fn store_and_get_group_key_works() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let member: AccountId = "member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner.clone());
        contract.register_group("test_group".to_string());
        contract.add_group_member("test_group".to_string(), member.clone());
        let key = BASE64_STANDARD.encode([0u8; 32]); // Valid 32-byte key
        contract.store_group_key("test_group".to_string(), key.clone());
        let context = get_context(member);
        testing_env!(context.build());
        let retrieved_key = contract.get_group_key("test_group".to_string());
        assert_eq!(retrieved_key, key);
    }

    #[test]
    #[should_panic(expected = "Only group owner can store key")]
    fn store_group_key_fails_non_owner() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let non_owner: AccountId = "not_owner.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner);
        contract.register_group("test_group".to_string());
        let context = get_context(non_owner);
        testing_env!(context.build());
        let key = BASE64_STANDARD.encode([0u8; 32]);
        contract.store_group_key("test_group".to_string(), key);
    }

    #[test]
    #[should_panic(expected = "Unauthorized")]
    fn get_group_key_fails_unauthorized() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let non_member: AccountId = "non_member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner.clone());
        contract.register_group("test_group".to_string());
        let key = BASE64_STANDARD.encode([0u8; 32]);
        contract.store_group_key("test_group".to_string(), key);
        let context = get_context(non_member);
        testing_env!(context.build());
        contract.get_group_key("test_group".to_string());
    }

    #[test]
    fn record_transaction_works() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let member: AccountId = "member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner.clone());
        contract.register_group("test_group".to_string());
        contract.add_group_member("test_group".to_string(), member.clone());
        let trans_id = contract.record_transaction(
            "test_group".to_string(),
            member.clone(),
            "file_hash".to_string(),
            "ipfs_hash".to_string(),
        );
        let transactions = contract.get_transactions_for_group("test_group".to_string(), member.clone());
        assert_eq!(transactions.len(), 1);
        assert_eq!(transactions[0].group_id, "test_group");
        assert_eq!(transactions[0].user_id, member.to_string());
        assert_eq!(transactions[0].file_hash, "file_hash");
        assert_eq!(transactions[0].ipfs_hash, "ipfs_hash");
        assert!(contract.transactions.contains_key(&trans_id));
    }

    #[test]
    #[should_panic(expected = "User not authorized")]
    fn record_transaction_fails_unauthorized() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let non_member: AccountId = "non_member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner.clone());
        contract.register_group("test_group".to_string());
        contract.record_transaction(
            "test_group".to_string(),
            non_member,
            "file_hash".to_string(),
            "ipfs_hash".to_string(),
        );
    }

    #[test]
    fn get_transactions_for_group_works() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let member: AccountId = "member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner.clone());
        contract.register_group("test_group".to_string());
        contract.add_group_member("test_group".to_string(), member.clone());
        contract.record_transaction(
            "test_group".to_string(),
            member.clone(),
            "file_hash1".to_string(),
            "ipfs_hash1".to_string(),
        );
        contract.record_transaction(
            "test_group".to_string(),
            member.clone(),
            "file_hash2".to_string(),
            "ipfs_hash2".to_string(),
        );
        let transactions = contract.get_transactions_for_group("test_group".to_string(), member.clone());
        assert_eq!(transactions.len(), 2);
        assert!(transactions.iter().any(|tx| tx.file_hash == "file_hash1" && tx.ipfs_hash == "ipfs_hash1"));
        assert!(transactions.iter().any(|tx| tx.file_hash == "file_hash2" && tx.ipfs_hash == "ipfs_hash2"));
    }

    #[test]
    #[should_panic(expected = "Unauthorized")]
    fn get_transactions_for_group_fails_unauthorized() {
        let owner: AccountId = "owner.testnet".parse().expect("Invalid AccountId");
        let non_member: AccountId = "non_member.testnet".parse().expect("Invalid AccountId");
        let context = get_context(owner.clone());
        testing_env!(context.build());
        let mut contract = Contract::new(owner.clone());
        contract.register_group("test_group".to_string());
        contract.get_transactions_for_group("test_group".to_string(), non_member);
    }
}