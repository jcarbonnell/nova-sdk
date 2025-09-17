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

    // Create a single account for both init and calls
    let owner_account = sandbox.dev_create_account().await?;

    // Initialize contract with owner as the caller
    let init_outcome = owner_account
        .call(&contract.id(), "new")
        .args_json(json!({"owner": owner_account.id().to_string()}))  // Use owner_account's ID
        .transact()
        .await?;
    assert!(init_outcome.is_success(), "{:#?}", init_outcome.into_result().unwrap_err());

    // Test register_group as owner
    let register_outcome = owner_account
        .call(&contract.id(), "register_group")
        .args_json(json!({"group_id": "test_group"}))
        .deposit(near_workspaces::types::NearToken::from_yoctonear(10_000_000_000_000_000_000_000)) // 0.01 NEAR
        .transact()
        .await?;
    assert!(register_outcome.is_success(), "{:#?}", register_outcome.into_result().unwrap_err());

    // Verify group exists (view call)
    let group_exists: bool = contract
        .view("groups_contains_key")
        .args_json(json!({"group_id": "test_group"}))
        .await?
        .json()?;
    assert!(group_exists, "Group should exist");

    Ok(())
}