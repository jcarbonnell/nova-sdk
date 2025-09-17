// NOVA contract version 0.1.0
use near_sdk::{env, log, near, AccountId, BorshStorageKey, PanicOnDefault};
use near_sdk::borsh::{BorshDeserialize, BorshSerialize};
use near_sdk::store::{LookupMap, Vector as StoreVec};

// Define the contract structure
#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Contract {
    owner: AccountId,
    groups: LookupMap<String, Group>,
    group_members: LookupMap<String, StoreVec<AccountId>>,
}

#[derive(BorshStorageKey, BorshSerialize)]
enum StorageKey {
    Groups,
    GroupMembers,
}

#[derive(BorshDeserialize, BorshSerialize, Clone)]
pub struct Group {
    owner: AccountId,
    group_key: Option<String>,
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
}

// The tests are not compiled into the final contract
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
}