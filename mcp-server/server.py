import os
from dotenv import load_dotenv
from fastmcp import FastMCP
import base64
import requests
import time
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import py_near
from py_near.account import Account
import asyncio
import json
import hashlib
import re

# Load .env variables
load_dotenv()

mcp = FastMCP(name="nova-mcp")

def _validate_near_key(private_key: str) -> str:
    """Light validation: base58, 64 chars (ed25519)."""
    if not private_key or len(private_key) < 64 or not re.match(r'^[1-9A-HJ-NP-Za-km-z]{64,}$', private_key):
        raise ValueError("Invalid NEAR private_key: Must be base58-encoded (64+ chars, no prefix).")
    return private_key

# Helper functions (callable internally)
async def _get_group_key(group_id: str, user_id: str, contract_id: str, private_key: str = None) -> str:
    """Internal: Retrieves key (async py_near calls)."""
    rpc = os.environ["RPC_URL"]
    private_key = private_key or os.environ.get("NEAR_PRIVATE_KEY", "")
    private_key = _validate_near_key(private_key)
    try:
        acc = Account(user_id, private_key, rpc)
        await acc.startup()
        result = await acc.view_function(
            contract_id=contract_id,
            method_name="get_group_key",
            args={"group_id": group_id, "user_id": user_id}
        )
        key = result.result  # Str base64
        if not key:
            raise Exception(f"No key for {group_id}/{user_id}")
        key_bytes = base64.b64decode(key)
        if len(key_bytes) != 32:
            raise Exception(f"Invalid key length: {len(key_bytes)}")
        print(f"Retrieved key for {group_id}/{user_id}: {key[:10]}...")  # Debug
        return key
    except Exception as e:
        if "Unauthorized" in str(e):
            raise Exception("Unauthorized access: Provide your group member account_id and private_key. Or request access from the group owner.")
        raise Exception(f"Get failed: {str(e)}")
    
async def _group_contains_key(group_id: str, contract_id: str) -> bool:
    """Internal: Check if group exists (view)."""
    rpc = os.environ["RPC_URL"]
    private_key = os.environ.get("NEAR_PRIVATE_KEY", "")  # Dummy
    acc = Account("dummy", private_key, rpc)  # Dummy for view
    await acc.startup()
    result = await acc.view_function(
        contract_id=contract_id,
        method_name="group_contains_key",
        args={"group_id": group_id}
    )
    return result.result

async def _is_authorized(group_id: str, user_id: str, contract_id: str) -> bool:
    """Internal: Check authorization (view)."""
    rpc = os.environ["RPC_URL"]
    private_key = os.environ.get("NEAR_PRIVATE_KEY", "")  # Dummy
    acc = Account(user_id, private_key, rpc)
    await acc.startup()
    result = await acc.view_function(
        contract_id=contract_id,
        method_name="is_authorized",
        args={"group_id": group_id, "user_id": user_id}
    )
    return result.result

def _encrypt_data(data: str, key: str) -> str:
    """Internal: Encrypts (same as tool)."""
    data_bytes = base64.b64decode(data)
    key_bytes = base64.b64decode(key)[:32]
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    pad_len = 16 - (len(data_bytes) % 16)
    padded = data_bytes + bytes([pad_len] * pad_len)
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + encrypted).decode('utf-8')

def _decrypt_data(encrypted: str, key: str) -> str:
    """Internal: Decrypts (same as tool)."""
    encrypted_bytes = base64.b64decode(encrypted)
    if len(encrypted_bytes) < 16:
        raise ValueError(f"Invalid encrypted data length: {len(encrypted_bytes)} (must be >=16 for IV)")
    key_bytes = base64.b64decode(key)[:32]
    iv = encrypted_bytes[:16]
    ciphertext = encrypted_bytes[16:]
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = decrypted_padded[-1]
    decrypted = decrypted_padded[:-pad_len]
    return base64.b64encode(decrypted).decode('utf-8')

def _ipfs_upload(encrypted_b64: str, filename: str) -> str:
    """Internal: Uploads (same as tool)."""
    encrypted_data = base64.b64decode(encrypted_b64)
    url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
    headers = {
        "pinata_api_key": os.environ["IPFS_API_KEY"],
        "pinata_secret_api_key": os.environ["IPFS_API_SECRET"]
    }
    files = {"file": (filename, encrypted_data)}
    response = requests.post(url, headers=headers, files=files)
    if response.status_code == 200:
        return response.json()["IpfsHash"]
    raise Exception(f"Upload failed: {response.text}")

async def _ipfs_retrieve(cid: str) -> str:
    """Internal: Retrieves data from IPFS via gateway (fallback to public)."""
    # Try custom gateway first
    gateway = os.environ.get("PINATA_GATEWAY", "").rstrip('/')
    if not gateway:
        gateway = "https://gateway.pinata.cloud/ipfs"
    url = f"{gateway}/{cid.lstrip('/').strip()}"
    if not cid.startswith('Qm'):
        raise Exception(f"Invalid CID: {cid}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200 and response.content:
                return base64.b64encode(response.content).decode('utf-8')
            elif response.status_code == 400:
                raise Exception(f"Invalid path/CID: {response.text[:100]}")
            elif response.status_code == 429:
                wait = 10 * (2 ** attempt)
                time.sleep(wait)
                continue
            else:
                raise Exception(f"Failed {response.status_code}: {response.text[:100]}")
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            # Fallback to public gateway on final fail
            if gateway != "https://gateway.pinata.cloud/ipfs":
                print(f"Custom gateway failed, falling back to public: {e}")
                gateway = "https://gateway.pinata.cloud/ipfs"
                url = f"{gateway}/{cid.lstrip('/').strip()}"
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 200 and response.content:
                    return base64.b64encode(response.content).decode('utf-8')
            raise e
    raise Exception(f"Failed after {max_retries} retries")

async def _record_near_transaction(group_id: str, user_id: str, file_hash: str, ipfs_hash: str, contract_id: str, account_id: str, private_key: str) -> str:
    """Internal: Records (async)."""
    rpc = os.environ["RPC_URL"]
    private_key = _validate_near_key(private_key)
    near = Account(account_id, private_key, rpc)
    await near.startup()  # Initialize account for async calls (added)
    result = await near.function_call(
        contract_id=contract_id,
        method_name="record_transaction",
        args={"group_id": group_id, "user_id": user_id, "file_hash": file_hash, "ipfs_hash": ipfs_hash},
        amount=int("2000000000000000000000")  # 0.002 NEAR yocto
    )
    if "SuccessValue" in result.status:
        trans_id = result.status['SuccessValue']  # Direct str/hex
        print(f"Recorded tx: {trans_id}")  # Log for debug (kept from failing)
        return trans_id
    raise Exception(f"Record failed (check owner auth): {result.status}. Authentication required: Provide your account_id and private_key as the smart contract owner. Or deploy your own contract via `near deploy` and pass `contract_id`.")

# Tools for direct external use (non-restricted)
@mcp.tool
def ipfs_upload(data: str, filename: str) -> str:
    """Uploads encrypted data to IPFS via Pinata and returns CID."""
    data_bytes = base64.b64decode(data)
    url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
    headers = {
        "pinata_api_key": os.environ["IPFS_API_KEY"],
        "pinata_secret_api_key": os.environ["IPFS_API_SECRET"]
    }
    files = {"file": (filename, data_bytes)}
    response = requests.post(url, headers=headers, files=files)
    if response.status_code == 200:
        return response.json()["IpfsHash"]
    raise Exception(f"Upload failed: {response.text}")

@mcp.tool
async def ipfs_retrieve(cid: str) -> str:  # Returns base64 bytes (now async)
    """Retrieves data from IPFS via Pinata gateway."""
    return await _ipfs_retrieve(cid)

@mcp.tool
def encrypt_data(data: str, key: str) -> str:  # Input b64 data/key; return b64 encrypted
    """Encrypts base64 data with AES-CBC key (32 bytes padded)."""
    return _encrypt_data(data, key)

@mcp.tool
def decrypt_data(encrypted: str, key: str) -> str:  # b64 in/out
    """Decrypts base64 encrypted data with AES-CBC key."""
    return _decrypt_data(encrypted, key)

# Tools for NOVA contract interaction (requires valid auth)
@mcp.tool
async def register_group(group_id: str, account_id: str = None, private_key: str = None, contract_id: str = None) -> str:
    """Registers new group on NOVA contract (owner only). Provide account_id/private_key as owner if not using default."""
    contract_id = contract_id or os.environ["CONTRACT_ID"]
    account_id = account_id or os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")
    private_key = _validate_near_key(private_key or os.environ.get("NEAR_PRIVATE_KEY", ""))
    rpc = os.environ["RPC_URL"]
    if await _group_contains_key(group_id, contract_id):
        raise Exception(f"Group {group_id} exists")
    near = Account(account_id, private_key, rpc)
    await near.startup()  # ADD THIS: Initialize account
    result = await near.function_call(
        contract_id=contract_id,
        method_name="register_group",
        args={"group_id": group_id},
        amount=int("100000000000000000000000")  # 0.01 NEAR yocto
    )
    if "SuccessValue" in result.status:
        print(f"Registered group: {group_id}")
        return "Registered"
    raise Exception(f"Register failed (check owner auth): {result.status}. Authentication required: Provide your account_id and private_key as the smart contract owner. Or deploy your own contract via `near deploy` and pass `contract_id`.")

@mcp.tool
async def add_group_member(group_id: str, member_id: str, account_id: str = None, private_key: str = None, contract_id: str = None) -> str:
    """Adds member to group (owner only). Provide account_id/private_key as owner if not using default."""
    contract_id = contract_id or os.environ["CONTRACT_ID"]
    account_id = account_id or os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")
    private_key = _validate_near_key(private_key or os.environ.get("NEAR_PRIVATE_KEY", ""))
    rpc = os.environ["RPC_URL"]
    if not await _group_contains_key(group_id, contract_id):
        raise Exception(f"Group {group_id} not found")
    if await _is_authorized(group_id, member_id, contract_id):
        raise Exception(f"User {member_id} already a member")
    near = Account(account_id, private_key, rpc)
    await near.startup()  # ADD THIS
    result = await near.function_call(
        contract_id=contract_id,
        method_name="add_group_member",
        args={"group_id": group_id, "user_id": member_id},
        amount=int("500000000000000000000")  # 0.0005 NEAR yocto
    )
    if "SuccessValue" in result.status:
        print(f"Added {member_id} to {group_id}")
        return "Added"
    raise Exception(f"Add failed (check owner auth): {result.status}. Authentication required: Provide your account_id and private_key as the smart contract owner. Or deploy your own contract via `near deploy` and pass `contract_id`.")

@mcp.tool
async def revoke_group_member(group_id: str, member_id: str, account_id: str = None, private_key: str = None, contract_id: str = None) -> str:
    """Revokes member from group (owner only, rotates key). Provide account_id/private_key as owner if not using default."""
    contract_id = contract_id or os.environ["CONTRACT_ID"]
    account_id = account_id or os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")
    private_key = _validate_near_key(private_key or os.environ.get("NEAR_PRIVATE_KEY", ""))
    rpc = os.environ["RPC_URL"]
    if not await _group_contains_key(group_id, contract_id):
        raise Exception(f"Group {group_id} not found")
    if not await _is_authorized(group_id, member_id, contract_id):
        raise Exception(f"User {member_id} not a member")
    near = Account(account_id, private_key, rpc)
    await near.startup()  # Initialize account for async calls
    result = await near.function_call(
        contract_id=contract_id,
        method_name="revoke_group_member",
        args={"group_id": group_id, "user_id": member_id},
        amount=int("500000000000000000000")  # 0.0005 NEAR yocto
    )
    if "SuccessValue" in result.status:
        print(f"Revoked {member_id} from {group_id}, key rotated")
        return "Revoked"
    raise Exception(f"Revoke failed (check owner auth): {result.status}. Authentication required: Provide your account_id and private_key as the smart contract owner. Or deploy your own contract via `near deploy` and pass `contract_id`.")

@mcp.tool
async def store_group_key(group_id: str, key: str, account_id: str = None, private_key: str = None, contract_id: str = None) -> str:
    """Stores symmetric key (base64, 32 bytes) for group on NOVA contract (owner only)."""
    contract_id = contract_id or os.environ["CONTRACT_ID"]
    account_id = account_id or os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")
    private_key = _validate_near_key(private_key or os.environ.get("NEAR_PRIVATE_KEY", ""))
    rpc = os.environ["RPC_URL"]
    key_bytes = base64.b64decode(key)
    if len(key_bytes) != 32:
        raise Exception(f"Invalid key length: {len(key_bytes)} (must be 32 bytes)")
    near = Account(account_id, private_key, rpc)
    await near.startup()  # Initialize account for async calls
    result = await near.function_call(
        contract_id=contract_id,
        method_name="store_group_key",
        args={"group_id": group_id, "key": key},
        amount=int("500000000000000000000")  # 0.0005 NEAR yocto
    )
    if "SuccessValue" in result.status:
        print(f"Key stored for {group_id}: {result.status['SuccessValue']}")
        return "Stored"
    raise Exception(f"Store failed (check owner auth): {result.status}. Authentication required: Provide your account_id and private_key as the smart contract owner. Or deploy your own contract via `near deploy` and pass `contract_id`.")

@mcp.tool
async def get_group_key(group_id: str, user_id: str, account_id: str = None, private_key: str = None, contract_id: str = None) -> str:
    """Retrieves symmetric key (base64, 32 bytes) for authorized user in group. Provide account_id/private_key as member if not using default."""
    contract_id = contract_id or os.environ["CONTRACT_ID"]
    account_id = account_id or user_id  # Use user_id as default account
    private_key = _validate_near_key(private_key or os.environ.get("NEAR_PRIVATE_KEY", ""))
    return await _get_group_key(group_id, user_id, contract_id, private_key)

@mcp.tool
async def record_near_transaction(group_id: str, user_id: str, file_hash: str, ipfs_hash: str, account_id: str = None, private_key: str = None, contract_id: str = None) -> str:
    """Records file tx on NOVA contract (owner only), returns trans_id. Provide creds as owner if not using default."""
    contract_id = contract_id or os.environ["CONTRACT_ID"]
    account_id = account_id or os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")
    private_key = _validate_near_key(private_key or os.environ.get("NEAR_PRIVATE_KEY", ""))
    return await _record_near_transaction(group_id, user_id, file_hash, ipfs_hash, contract_id, account_id, private_key)

@mcp.tool
async def composite_upload(group_id: str, user_id: str, data: str, filename: str, account_id: str = None, private_key: str = None, contract_id: str = None) -> dict:
    """Full upload: get_key → encrypt → IPFS pin → record tx (owner for record). Provide creds as owner/member."""
    contract_id = contract_id or os.environ["CONTRACT_ID"]
    account_id = account_id or os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")
    private_key = _validate_near_key(private_key or os.environ.get("NEAR_PRIVATE_KEY", ""))
    try:
        # Step 1: Fetch key (uses _get_group_key, which has startup)
        key = await _get_group_key(group_id, user_id, contract_id, private_key)
        # Step 2: Encrypt data
        encrypted_b64 = _encrypt_data(data, key)
        # Step 3: Upload (direct)
        cid = _ipfs_upload(encrypted_b64, filename)
        # Step 4: Local hash
        file_hash = hashlib.sha256(base64.b64decode(data)).hexdigest()
        # Step 5: Blockchain record (uses _record_near_transaction, which needs startup—ensure it's added there if not)
        trans_id = await _record_near_transaction(group_id, user_id, file_hash, cid, contract_id, account_id, private_key)
        print(f"Composite success: CID={cid}, Trans={trans_id}")
        return {"cid": cid, "trans_id": trans_id, "file_hash": file_hash}
    except Exception as e:
        raise Exception(f"Composite upload failed: {str(e)}")

@mcp.tool
async def composite_retrieve(group_id: str, ipfs_hash: str, account_id: str = None, private_key: str = None, contract_id: str = None) -> dict:
    """Full retrieve: get_key (member) → fetch IPFS → decrypt. Returns {'decrypted_b64': str, 'file_hash': str (for verification)}."""
    contract_id = contract_id or os.environ["CONTRACT_ID"]
    account_id = account_id or os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")
    private_key = _validate_near_key(private_key or os.environ.get("NEAR_PRIVATE_KEY", ""))
    if not ipfs_hash.startswith('Qm'):
        raise Exception(f"Invalid CID: {ipfs_hash}")
    try:
        # Step 1: Fetch key (member auth)
        key = await _get_group_key(group_id, account_id, contract_id, private_key)
        # Step 2: Fetch from IPFS (use internal)
        encrypted_b64 = await _ipfs_retrieve(ipfs_hash)
        # Step 3: Decrypt (use internal)
        decrypted_b64 = _decrypt_data(encrypted_b64, key)
        # Step 4: Hash for verification (user-side compare to on-chain)
        decrypted_data = base64.b64decode(decrypted_b64)
        file_hash = hashlib.sha256(decrypted_data).hexdigest()
        print(f"Composite retrieve success: {len(decrypted_data)} bytes, hash={file_hash}")
        return {"decrypted_b64": decrypted_b64, "file_hash": file_hash}
    except Exception as e:
        raise Exception(f"Composite retrieve failed: {str(e)}")

@mcp.tool
async def auth_status(user_id: str, group_id: str = "test_group") -> dict:
    """Tool: Check user auth/groups on NOVA contract. Returns {'authorized': bool, 'groups': list[str], 'member_count': int}."""
    contract_id = os.environ["CONTRACT_ID"]
    rpc = os.environ["RPC_URL"]
    private_key = os.environ.get("NEAR_PRIVATE_KEY", "")  # Dummy for views
    try:
        acc = Account(user_id, private_key, rpc)
        await acc.startup()
        # Check authorized
        auth_result = await acc.view_function(
            contract_id=contract_id,
            method_name="is_authorized",
            args={"group_id": group_id, "user_id": user_id}
        )
        authorized = auth_result.result
        # List user's groups via transactions (filter unique; assume default if none)
        txs_result = await acc.view_function(
            contract_id=contract_id,
            method_name="get_transactions_for_group",
            args={"group_id": group_id, "user_id": user_id}  # Reuse for sample; expand to all if multi-view added
        )
        groups = list(set(tx["group_id"] for tx in txs_result.result)) if txs_result.result else [group_id]
        member_count = len(groups)
        print(f"Auth for {user_id} in {group_id}: authorized={authorized}, groups={groups}")
        return {"authorized": authorized, "groups": groups, "member_count": member_count}
    except Exception as e:
        if "Unauthorized" in str(e):
            return {"authorized": False, "groups": [], "member_count": 0}
        raise Exception(f"Auth query failed: {str(e)}")

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)