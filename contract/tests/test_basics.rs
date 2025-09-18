//nova-sdk/contract/tests/test_basics.rs
use near_workspaces;
use serde_json::json;

#[tokio::test]
async fn test_contract_is_operational() -> Result<(), Box<dyn std::error::Error>> {
    let contract_wasm = near_workspaces::compile_project("./").await?;
    test_basics_on(&contract_wasm).await?;
    Ok(())
}

async fn test_basics_on(contract_wasm: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    let sandbox = near_workspaces::sandbox().await?;
    let contract = sandbox.dev_deploy(contract_wasm).await?;
    let owner_account = sandbox.dev_create_account().await?;
    let member_account = sandbox.dev_create_account().await?;

    // Initialize contract
    let init_outcome = owner_account
        .call(&contract.id(), "new")
        .args_json(json!({"owner": owner_account.id().to_string()}))  // Use owner_account's ID
        .transact()
        .await?;
    assert!(init_outcome.is_success(), "{:#?}", init_outcome.into_result().unwrap_err());

    // Test register_group
    let register_outcome = owner_account
        .call(&contract.id(), "register_group")
        .args_json(json!({"group_id": "test_group"}))
        .deposit(near_workspaces::types::NearToken::from_yoctonear(10_000_000_000_000_000_000_000)) // 0.01 NEAR
        .transact()
        .await?;
    assert!(register_outcome.is_success(), "{:#?}", register_outcome.into_result().unwrap_err());

    // Verify group exists
    let group_exists: bool = contract
        .view("groups_contains_key")
        .args_json(json!({"group_id": "test_group"}))
        .await?
        .json()?;
    assert!(group_exists, "Group should exist");

    // Test add_group_member
    let add_outcome = owner_account
        .call(&contract.id(), "add_group_member")
        .args_json(json!({"group_id": "test_group", "user_id": member_account.id().to_string()}))
        .deposit(near_workspaces::types::NearToken::from_yoctonear(500_000_000_000_000_000_000)) // 0.0005 NEAR
        .transact()
        .await?;
    assert!(add_outcome.is_success(), "{:#?}", add_outcome.into_result().unwrap_err());

    // Verify is_authorized
    let is_authorized: bool = contract
        .view("is_authorized")
        .args_json(json!({"group_id": "test_group", "user_id": member_account.id().to_string()}))
        .await?
        .json()?;
    assert!(is_authorized, "Member should be authorized");

    // Test revoke_group_member
    let revoke_outcome = owner_account
        .call(&contract.id(), "revoke_group_member")
        .args_json(json!({"group_id": "test_group", "user_id": member_account.id().to_string()}))
        .deposit(near_workspaces::types::NearToken::from_yoctonear(500_000_000_000_000_000_000)) // 0.0005 NEAR
        .transact()
        .await?;
    assert!(revoke_outcome.is_success(), "{:#?}", revoke_outcome.into_result().unwrap_err());

    // Verify is_authorized after revoke
    let is_authorized: bool = contract
        .view("is_authorized")
        .args_json(json!({"group_id": "test_group", "user_id": member_account.id().to_string()}))
        .await?
        .json()?;
    assert!(!is_authorized, "Member should not be authorized");

    // Test store_group_key
    let key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="; // base64 of 32 zero bytes
    let store_key_outcome = owner_account
        .call(&contract.id(), "store_group_key")
        .args_json(json!({"group_id": "test_group", "key": key}))
        .deposit(near_workspaces::types::NearToken::from_yoctonear(500_000_000_000_000_000_000)) // 0.0005 NEAR
        .transact()
        .await?;
    assert!(store_key_outcome.is_success(), "{:#?}", store_key_outcome.into_result().unwrap_err());

    // Add member again for get_group_key test
    let add_outcome = owner_account
        .call(&contract.id(), "add_group_member")
        .args_json(json!({"group_id": "test_group", "user_id": member_account.id().to_string()}))
        .deposit(near_workspaces::types::NearToken::from_yoctonear(500_000_000_000_000_000_000))
        .transact()
        .await?;
    assert!(add_outcome.is_success(), "{:#?}", add_outcome.into_result().unwrap_err());

    // Test get_group_key
    let get_key_outcome = member_account
        .call(&contract.id(), "get_group_key")
        .args_json(json!({"group_id": "test_group"}))
        .gas(near_workspaces::types::Gas::from_tgas(100))
        .transact()
        .await?;
    let get_key_result: String = get_key_outcome.json()?;
    assert_eq!(get_key_result, key, "Key should match stored key");

    // Test record_transaction
    let record_outcome = owner_account
        .call(&contract.id(), "record_transaction")
        .args_json(json!({
            "group_id": "test_group",
            "user_id": member_account.id().to_string(),
            "file_hash": "file_hash",
            "ipfs_hash": "ipfs_hash"
        }))
        .deposit(near_workspaces::types::NearToken::from_yoctonear(1_000_000_000_000_000_000_000)) // 0.001 NEAR
        .transact()
        .await?;
    assert!(record_outcome.is_success(), "{:#?}", record_outcome.into_result().unwrap_err());

    // Test get_transactions_for_group
    let transactions: Vec<serde_json::Value> = member_account
        .view(&contract.id(), "get_transactions_for_group")
        .args_json(json!({
            "group_id": "test_group",
            "user_id": member_account.id().to_string()
        }))
        .await?
        .json()?;
    assert_eq!(transactions.len(), 1, "Should have one transaction");
    assert_eq!(transactions[0]["user_id"], member_account.id().to_string());
    assert_eq!(transactions[0]["file_hash"], "file_hash");
    assert_eq!(transactions[0]["ipfs_hash"], "ipfs_hash");

    Ok(())
}