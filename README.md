# NOVA-SDK

NOVA is a privacy-first, decentralized file-sharing primitive for NEAR dApps, empowering user-owned AI at scale. NOVA enables secure storage and sharing of sensitive data (e.g., datasets for AI agent fine-tuning) without centralized intermediaries, leveraging group key management, IPFS, and NEAR smart contracts.

NOVA fills critical gaps in NEAR’s ecosystem —no native encrypted persistence for TEEs, Intents, or Shade Agents— while inheriting NEAR’s strengths like sharding for scalability, low-cost transactions (~0.01 NEAR/gas), and AI-native tools (e.g., NEAR AI CLI). Whether you're building AI social platforms, DeFi apps, or autonomous agent workflows, NOVA provides a secure, verifiable data layer.

## Why Use NOVA?

- **Privacy-First**: Encrypt files with group keys, ensuring only authorized users or AI agents access data, critical for AI data pipelines where tampering could bias models.
- **Decentralized**: Store files on IPFS, log metadata on NEAR’s immutable ledger, and manage access via smart contracts. No central servers.
- **AI-Ready**: Seamlessly integrates with NEAR’s TEEs, Intents, and Shade Agents, enabling secure data for AI training and execution.
- **Developer-Friendly**: Free-to-integrate SDK (Rust crate and JS package) with pay-per-action fees baked into the contract, blending into your dApp’s backend.

## Key Features

- **Group Creation & Management**: Owners (NEAR AccountIds) create groups via smart contracts, supporting collaborative AI training with multi-group membership.
- **Access Control**: Smart contracts maintain a mapping table for group keys and members, ensuring only authorized users access files, vital for user-owned AI privacy.
- **Secure Storage**: Files are encrypted with group keys and pinned to IPFS, optimized for AI dApps (e.g., datasets for fine-tuning).
- **Access Workflow**: Authorized users query on-chain metadata, retrieve encrypted files from IPFS, and receive wrapped keys for local decryption, ensuring verifiable access.
- **Revocation & Key Rotation**: Remove members and rotate keys with lazy re-encryption to minimize latency/gas costs for large groups.
- **Integrity & Trackability**: Log signed transactions (with file hashes) on-chain for non-corruption guarantees, leveraging NEAR’s ledger for verifiability.

## NOVA x NEAR Ecosystem

NOVA complements NEAR’s AI-focused tools:
- **TEEs**: Secures data at rest/transit for confidential compute (e.g., private AI inference in Phala enclaves).
- **Intents**: Gates solver access to encrypted payloads, enabling private, AI-driven fulfillment (e.g., cross-chain swaps).
- **Shade Agents**: Persists off-chain data for autonomous workers, resolving the "oracle problem" with verified inputs (e.g., prediction markets).

### Potential add to the NOVA-SDK
- Implement the pay-per-action model by adding fees to #[payable] methods. Setup fees to nova-sdk.near.
- Allow agents/members to record_transaction so they can upload files (currently only owner)
- Allow manager- storage-agent's call get_transactions_for_group to list files.

- Add view for group_members? so anyone can see who's in that group?
- Reinforce Access Control with Token Holding (e.g. Access Token NFTs)
- Automate Metadata Extraction with AI to optimise storage/retrieval on IPFS (e.g. indexing with augmented file metadata)
- Add price to transaction so file owners can monetize their datasets to be accessed through IPFS.