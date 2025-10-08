use nova_sdk_rs::{NovaSdk, NovaError};

#[tokio::test]
async fn test_get_balance_integration() {
    let sdk = NovaSdk::new(
        "https://rpc.testnet.near.org",
        "nova-sdk-2.testnet",
        "fake_key",
        "fake_secret"
    );
    
    // Query balance for a known testnet account
    let balance = sdk.get_balance("nova-sdk-2.testnet").await.unwrap();
    
    // Balance should be a valid u128 (yoctoNEAR)
    assert!(balance > 0, "Balance should be greater than 0 for an active account");
}

#[tokio::test]
async fn test_get_balance_nonexistent_account() {
    let sdk = NovaSdk::new(
        "https://rpc.testnet.near.org",
        "nova-sdk-2.testnet",
        "fake_key",
        "fake_secret"
    );
    
    // Try to query balance for a likely nonexistent account
    let result = sdk.get_balance("this-account-definitely-does-not-exist-12345.testnet").await;
    
    // Should return an error
    assert!(result.is_err(), "Should fail for nonexistent account");
    match result {
        Err(NovaError::Near(_)) => {}, // Expected error
        _ => panic!("Expected NovaError::Near for nonexistent account"),
    }
}

#[tokio::test]
async fn test_with_signer_integration() {
    // Note: This uses an invalid key, so it will fail at the signing stage
    // In a real integration test, you'd use a valid test account and key
    let sdk = NovaSdk::new(
        "https://rpc.testnet.near.org",
        "nova-sdk-2.testnet",
        "fake_key",
        "fake_secret"
    );
    
    let result = sdk.with_signer(
        "ed25519:invalidkeyformatfortesting123456",
        "test.testnet"
    );
    
    // Should fail due to invalid key format
    assert!(result.is_err());
    assert!(matches!(result.unwrap_err(), NovaError::Signing(_)));
}

#[tokio::test]
async fn test_sdk_initialization() {
    let sdk = NovaSdk::new(
        "https://rpc.testnet.near.org",
        "nova-sdk-2.testnet",
        "test_pinata_key",
        "test_pinata_secret"
    );
    
    // Just verify the SDK can be created without panicking
    // and can make a simple RPC call
    let result = sdk.get_balance("nova-sdk-2.testnet").await;
    assert!(result.is_ok(), "SDK should be able to make basic RPC calls");
}

#[tokio::test]
async fn test_invalid_account_id_format() {
    let sdk = NovaSdk::new(
        "https://rpc.testnet.near.org",
        "nova-sdk-2.testnet",
        "fake_key",
        "fake_secret"
    );
    
    // Test various invalid account formats
    let invalid_accounts = vec![
        "invalid@account",
        "UPPERCASE.testnet",
        "has space.testnet",
        "has_underscore",
        "",
    ];
    
    for invalid_account in invalid_accounts {
        let result = sdk.get_balance(invalid_account).await;
        assert!(result.is_err(), "Should fail for invalid account: {}", invalid_account);
    }
}

// Real signer test - only runs if environment variables are set
#[tokio::test]
async fn test_with_real_signer() {
    // Skip test if credentials not available
    let private_key = match std::env::var("TEST_NEAR_PRIVATE_KEY") {
        Ok(key) => key,
        Err(_) => {
            println!("Skipping test_with_real_signer: TEST_NEAR_PRIVATE_KEY not set");
            return;
        }
    };
    
    let account_id = match std::env::var("TEST_NEAR_ACCOUNT_ID") {
        Ok(id) => id,
        Err(_) => {
            println!("Skipping test_with_real_signer: TEST_NEAR_ACCOUNT_ID not set");
            return;
        }
    };
    
    let sdk = NovaSdk::new(
        "https://rpc.testnet.near.org",
        "nova-sdk-2.testnet",
        "fake_key",
        "fake_secret"
    ).with_signer(&private_key, &account_id).unwrap();
    
    // Verify we can query the account we signed with
    let balance = sdk.get_balance(&account_id).await.unwrap();
    assert!(balance > 0, "Account should have a positive balance");
    
    println!("✅ Successfully authenticated with account: {}", account_id);
    println!("   Balance: {} yoctoNEAR", balance);
}