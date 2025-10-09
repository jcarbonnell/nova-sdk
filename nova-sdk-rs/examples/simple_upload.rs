use nova_sdk_rs::{NovaSdk};
use std::env;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Load from env (set via .env or export)
    let rpc_url = env::var("RPC_URL").unwrap_or_else(|_| "https://rpc.testnet.near.org".to_string());
    let contract_id = env::var("CONTRACT_ID").unwrap_or_else(|_| "nova-sdk-2.testnet".to_string());
    let pinata_key = env::var("PINATA_API_KEY").expect("PINATA_API_KEY required");
    let pinata_secret = env::var("PINATA_SECRET_KEY").expect("PINATA_SECRET_KEY required");
    let private_key = env::var("TEST_NEAR_PRIVATE_KEY").expect("TEST_NEAR_PRIVATE_KEY required");
    let account_id = env::var("TEST_NEAR_ACCOUNT_ID").expect("TEST_NEAR_ACCOUNT_ID required");
    let group_id = "test_group";

    // Initialize SDK
    let sdk = NovaSdk::new(&rpc_url, &contract_id, &pinata_key, &pinata_secret)
        .with_signer(&private_key, &account_id)?;

    // Sample data (binary-safe)
    let data = b"Hello, secure NOVA world!";

    // Upload
    let upload_result = sdk.composite_upload(group_id, &account_id, data, "example.txt").await?;
    println!("✅ Upload Success:");
    println!("  CID: {}", upload_result.cid);
    println!("  Transaction ID: {}", upload_result.trans_id);
    println!("  File Hash: {}", upload_result.file_hash);

    // Retrieve
    let retrieve_result = sdk.composite_retrieve(group_id, &upload_result.cid).await?;
    println!("\n✅ Retrieve Success:");
    println!("  Retrieved Data: {:?}", retrieve_result.data);
    println!("  Verified Hash: {}", retrieve_result.file_hash);
    assert_eq!(retrieve_result.data, data, "Data mismatch on roundtrip!");

    println!("\n🎉 End-to-end secure file sharing complete.");
    Ok(())
}