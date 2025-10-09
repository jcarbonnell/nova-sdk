use nova_sdk_rs::NovaSdk;
use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use std::env;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Load from env
    let rpc_url = env::var("RPC_URL").unwrap_or_else(|_| "https://rpc.testnet.near.org".to_string());
    let contract_id = env::var("CONTRACT_ID").unwrap_or_else(|_| "nova-sdk-2.testnet".to_string());
    let private_key = env::var("TEST_NEAR_PRIVATE_KEY").expect("TEST_NEAR_PRIVATE_KEY required");
    let account_id = env::var("TEST_NEAR_ACCOUNT_ID").expect("TEST_NEAR_ACCOUNT_ID required");

    // Initialize SDK
    let sdk = NovaSdk::new(&rpc_url, &contract_id, "dummy", "dummy")
        .with_signer(&private_key, &account_id)?;

    let group_id = "rotation_test";

    // Store initial key (generate 32-byte random)
    use rand::RngCore;
    let mut key_bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut key_bytes);
    let key_b64 = STANDARD.encode(key_bytes);
    sdk.store_group_key(group_id, &key_b64).await?;
    println!("✅ Initial key stored for group '{}': {}", group_id, &key_b64[..20]);  // Truncated for display

    // Fetch initial key (as authorized owner)
    let initial_key = sdk.get_group_key(group_id, &account_id).await?;
    println!("🔑 Initial key retrieved: {}", &initial_key[..20]);
    assert_eq!(initial_key, key_b64, "Key mismatch on store/fetch!");

    // Simulate revocation (triggers rotation in contract)
    let revoked_member = "revoked.testnet";  // Dummy; assumes add_member done prior
    sdk.revoke_group_member(group_id, revoked_member).await?;
    println!("✅ Revocation triggered key rotation for group '{}'.", group_id);

    // Fetch new key
    let rotated_key = sdk.get_group_key(group_id, &account_id).await?;
    println!("🔄 Rotated key retrieved: {}", &rotated_key[..20]);
    assert_ne!(rotated_key, initial_key, "Key should have rotated!");

    println!("\n🎉 Key rotation demo complete. Old key: {}, New key: {}", &initial_key[..20], &rotated_key[..20]);
    Ok(())
}