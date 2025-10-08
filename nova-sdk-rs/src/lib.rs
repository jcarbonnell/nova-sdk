use near_jsonrpc_client::{methods, JsonRpcClient};
use near_jsonrpc_primitives::types::query::QueryResponseKind as JsonRpcQueryResponseKind;
use near_primitives::types::{AccountId, Balance, BlockReference, Finality};
use near_primitives::views::QueryRequest;
use near_crypto::{InMemorySigner, Signer, SecretKey};
use thiserror::Error;
use std::str::FromStr;

#[derive(Error, Debug)]
pub enum NovaError {
    #[error("Near RPC error: {0}")]
    Near(String),
    #[error("Invalid key length or format")]
    InvalidKey,
    #[error("Account ID parse failed")]
    ParseAccount,
    #[error("Signing error: {0}")]
    Signing(String),
}

#[derive(Debug)]
pub struct NovaSdk {
    client: JsonRpcClient,
    contract_id: AccountId,
    signer: Option<Signer>,
    pinata_key: String,
    pinata_secret: String,
}

impl NovaSdk {
    /// Creates a new NovaSdk instance.
    pub fn new(rpc_url: &str, contract_id: &str, pinata_key: &str, pinata_secret: &str) -> Self {
        let client = JsonRpcClient::connect(rpc_url);
        let contract_id = AccountId::from_str(contract_id).expect("Invalid contract_id format");
        NovaSdk {
            client,
            contract_id,
            signer: None,
            pinata_key: pinata_key.to_string(),
            pinata_secret: pinata_secret.to_string(),
        }
    }

    /// Attaches a signer using a NEAR private key string (e.g., "ed25519:base58key").
    pub fn with_signer(mut self, private_key: &str, account_id: &str) -> Result<Self, NovaError> {
        // Validate account_id first
        let account_id_acc = AccountId::from_str(account_id).map_err(|_| NovaError::ParseAccount)?;
        // Then parse the secret key
        let secret_key = SecretKey::from_str(private_key).map_err(|e| NovaError::Signing(e.to_string()))?;
        let signer = InMemorySigner::from_secret_key(account_id_acc, secret_key);
        self.signer = Some(signer);
        Ok(self)
    }

    /// Queries the balance of an account on NEAR.
    pub async fn get_balance(&self, account_id: &str) -> Result<Balance, NovaError> {
        let account_id_acc = AccountId::from_str(account_id).map_err(|_| NovaError::ParseAccount)?;
        let request = methods::query::RpcQueryRequest {
            block_reference: BlockReference::Finality(Finality::Final),
            request: QueryRequest::ViewAccount { account_id: account_id_acc },
        };
        let response = self.client.call(request).await.map_err(|e| NovaError::Near(e.to_string()))?;
        match response.kind {
            JsonRpcQueryResponseKind::ViewAccount(acc) => Ok(acc.amount),
            _ => Err(NovaError::Near("Invalid response kind".to_string())),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_new() {
        let sdk = NovaSdk::new(
            "https://rpc.testnet.near.org",
            "nova-sdk-2.testnet",
            "fake_key",
            "fake_secret",
        );
        assert_eq!(sdk.contract_id.as_str(), "nova-sdk-2.testnet");
        assert!(sdk.signer.is_none());
    }

    #[tokio::test]
    async fn test_with_signer_valid_format() {
        // Dummy valid-format key (expects Signing err on invalid base58, but tests parse call)
        let private_key = "ed25519:ABC123dummybase58key32bytesencodedhereforrusttest";
        let account_id = "test.account.testnet";
        let result = NovaSdk::new("https://rpc.testnet.near.org", "nova-sdk-2.testnet", "fake", "fake")
            .with_signer(private_key, account_id);
        // Expects Signing error (invalid base58), but no panic/crash
        assert!(matches!(result.err().unwrap(), NovaError::Signing(_)));
    }

    #[tokio::test]
    async fn test_with_signer_invalid_account() {
        let private_key = "ed25519:dummy";
        let invalid_account = "invalid@account";
        let result = NovaSdk::new("https://rpc.testnet.near.org", "nova-sdk-2.testnet", "fake", "fake")
            .with_signer(private_key, invalid_account);
        assert!(matches!(result.err().unwrap(), NovaError::ParseAccount));
    }

    #[tokio::test]
    async fn test_get_balance() {
        let sdk = NovaSdk::new(
            "https://rpc.testnet.near.org",
            "nova-sdk-2.testnet",
            "fake_key",
            "fake_secret",
        );
        let balance = sdk.get_balance("nova-sdk-2.testnet").await.unwrap();
        let bal_str = balance.to_string();
        assert!(!bal_str.is_empty()); // Valid yoctoNEAR like "123..."
        assert!(bal_str.parse::<u128>().is_ok()); // Ensures it's a number string
    }
}