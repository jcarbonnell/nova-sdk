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

# Load .env variables
load_dotenv()

mcp = FastMCP(name="nova-mcp")

# Helper functions (callable internally)
async def _get_group_key(group_id: str, user_id: str) -> str:
    """Internal: Retrieves key (async py_near calls)."""
    contract_id = os.environ["CONTRACT_ID"]
    rpc = os.environ["RPC_URL"]
    private_key = os.environ.get("NEAR_PRIVATE_KEY", "")  # Dummy for view
    try:
        acc = Account(user_id, private_key, rpc)
        await acc.startup()  # Await directly (no asyncio.run)
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
            raise Exception(f"Unauthorized for {group_id}/{user_id}")
        raise Exception(f"Get failed: {str(e)}")
    
async def _group_contains_key(group_id: str) -> bool:
    """Internal: Check if group exists (view)."""
    contract_id = os.environ["CONTRACT_ID"]
    rpc = os.environ["RPC_URL"]
    private_key = os.environ.get("NEAR_PRIVATE_KEY", "")  # Dummy
    acc = Account("nova-sdk-2.testnet", private_key, rpc)  # Use default signer for view
    await acc.startup()
    result = await acc.view_function(
        contract_id=contract_id,
        method_name="group_contains_key",
        args={"group_id": group_id}
    )
    return result.result

async def _is_authorized(group_id: str, user_id: str) -> bool:
    """Internal: Check authorization (view)."""
    contract_id = os.environ["CONTRACT_ID"]
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

async def _record_near_transaction(group_id: str, user_id: str, file_hash: str, ipfs_hash: str) -> str:
    """Internal: Records (async)."""
    contract_id = os.environ["CONTRACT_ID"]
    private_key = os.environ["NEAR_PRIVATE_KEY"]
    rpc = os.environ["RPC_URL"]
    signer = os.environ.get("SIGNER_ACCOUNT_ID", user_id)
    near = Account(signer, private_key, rpc)
    result = await near.function_call(
        contract_id=contract_id,
        method_name="record_transaction",
        args={"group_id": group_id, "user_id": user_id, "file_hash": file_hash, "ipfs_hash": ipfs_hash},
        amount=int("2000000000000000000000")  # 0.002 NEAR
    )
    if "SuccessValue" in result.status:
        return result.status['SuccessValue']
    raise Exception(f"Record failed: {result.status}")

# Tools for direct external use
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
def ipfs_retrieve(cid: str) -> str:  # Returns base64 bytes
    """Retrieves data from IPFS via Pinata gateway."""
    gateway = os.environ.get("PINATA_GATEWAY", "https://gateway.pinata.cloud/ipfs").rstrip('/')
    url = f"{gateway}/ipfs/{cid.lstrip('/').strip()}"
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
            raise e
    raise Exception(f"Failed after {max_retries} retries")

@mcp.tool
def encrypt_data(data: str, key: str) -> str:  # Input b64 data/key; return b64 encrypted
    """Encrypts base64 data with AES-CBC key (32 bytes padded)."""
    data_bytes = base64.b64decode(data)
    key_bytes = base64.b64decode(key)[:32]
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    pad_len = 16 - (len(data_bytes) % 16)
    padded = data_bytes + bytes([pad_len] * pad_len)
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + encrypted).decode('utf-8')

@mcp.tool
def decrypt_data(encrypted: str, key: str) -> str:  # b64 in/out
    """Decrypts base64 encrypted data with AES-CBC key."""
    encrypted_bytes = base64.b64decode(encrypted)
    key_bytes = base64.b64decode(key)[:32]
    iv = encrypted_bytes[:16]
    ciphertext = encrypted_bytes[16:]
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = decrypted_padded[-1]
    decrypted = decrypted_padded[:-pad_len]
    return base64.b64encode(decrypted).decode('utf-8')

@mcp.tool
async def record_near_transaction(group_id: str, user_id: str, file_hash: str, ipfs_hash: str) -> str:
    """Records file tx on NOVA contract, returns trans_id."""
    contract_id = os.environ["CONTRACT_ID"]
    private_key = os.environ["NEAR_PRIVATE_KEY"]
    rpc = os.environ["RPC_URL"]
    signer = os.environ.get("SIGNER_ACCOUNT_ID", user_id)  # Use signer if set
    near = Account(signer, private_key, rpc)
    result = await near.function_call(
        contract_id=contract_id,
        method_name="record_transaction",
        args={"group_id": group_id, "user_id": user_id, "file_hash": file_hash, "ipfs_hash": ipfs_hash},
        amount=int("2000000000000000000000")  # 0.002 NEAR yocto
    )
    if "SuccessValue" in result.status:
        trans_id = result.status['SuccessValue']  # Direct str/hex
        print(f"Recorded tx: {trans_id}")  # Log for debug
        return trans_id
    raise Exception(f"Record failed: {result.status}")

@mcp.tool
async def store_group_key(group_id: str, key: str) -> str:
    """Stores symmetric key (base64, 32 bytes) for group on NOVA contract. Returns 'Stored'."""
    contract_id = os.environ["CONTRACT_ID"]
    private_key = os.environ["NEAR_PRIVATE_KEY"]
    rpc = os.environ["RPC_URL"]
    signer = os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")  # Owner/signer
    near = Account(signer, private_key, rpc)
    # Validate key locally (32 bytes post-decode)
    key_bytes = base64.b64decode(key)
    if len(key_bytes) != 32:
        raise Exception(f"Invalid key length: {len(key_bytes)} (must be 32 bytes)")
    result = await near.function_call(
        contract_id=contract_id,
        method_name="store_group_key",
        args={"group_id": group_id, "key": key},
        amount=int("500000000000000000000")  # 0.0005 NEAR yocto
    )
    if "SuccessValue" in result.status:
        print(f"Key stored for {group_id}: {result.status['SuccessValue']}")
        return "Stored"
    raise Exception(f"Store failed: {result.status}")

@mcp.tool
async def get_group_key(group_id: str, user_id: str) -> str:
    """Retrieves symmetric key (base64, 32 bytes) for authorized user in group. Raises if unauthorized/no key."""
    contract_id = os.environ["CONTRACT_ID"]
    rpc = os.environ["RPC_URL"]
    private_key = os.environ.get("NEAR_PRIVATE_KEY", "")  # Dummy ok for view
    try:
        acc = Account(user_id, private_key, rpc)  # Use user_id as account
        await acc.startup()  # Async init
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
        print(f"Retrieved key for {group_id}/{user_id}: {key[:10]}...")
        return key
    except Exception as e:
        if "Unauthorized" in str(e):
            raise Exception(f"Unauthorized for {group_id}/{user_id}")
        raise Exception(f"Get failed: {str(e)}")
    
@mcp.tool
async def composite_upload(group_id: str, user_id: str, data: str, filename: str) -> dict:
    """Full upload: get_key → encrypt → IPFS pin → record tx. Args: b64 data. Returns {'cid': str, 'trans_id': str, 'file_hash': str}."""
    try:
        # Step 1: Fetch key (for user/group)
        key = await _get_group_key(group_id, user_id)
        # Step 2: Encrypt data
        encrypted_b64 = _encrypt_data(data, key)
        # Step 3: Upload (direct)
        cid = _ipfs_upload(encrypted_b64, filename)
        # Step 4: Local hash
        file_hash = hashlib.sha256(base64.b64decode(data)).hexdigest()
        # Step 5: Blockchain record (direct async awaits for onchain validation)
        trans_id = await _record_near_transaction(group_id, user_id, file_hash, cid)
        print(f"Composite success: CID={cid}, Trans={trans_id}")
        return {"cid": cid, "trans_id": trans_id, "file_hash": file_hash}
    except Exception as e:
        raise Exception(f"Composite upload failed: {str(e)}")

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
    
@mcp.tool
async def register_group(group_id: str) -> str:
    """Registers new group on NOVA contract (owner only). Returns 'Registered'."""
    contract_id = os.environ["CONTRACT_ID"]
    private_key = os.environ["NEAR_PRIVATE_KEY"]
    rpc = os.environ["RPC_URL"]
    signer = os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")  # Assume owner
    # Check if exists first
    if await _group_contains_key(group_id):
        raise Exception(f"Group {group_id} exists")
    near = Account(signer, private_key, rpc)
    result = await near.function_call(
        contract_id=contract_id,
        method_name="register_group",
        args={"group_id": group_id},
        amount=int("100000000000000000000000")  # 0.01 NEAR yocto
    )
    if "SuccessValue" in result.status:
        print(f"Registered group: {group_id}")
        return "Registered"
    raise Exception(f"Register failed: {result.status}")

@mcp.tool
async def add_group_member(group_id: str, member_id: str) -> str:
    """Adds member to group (owner only). Returns 'Added'."""
    contract_id = os.environ["CONTRACT_ID"]
    private_key = os.environ["NEAR_PRIVATE_KEY"]
    rpc = os.environ["RPC_URL"]
    signer = os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")  # Owner
    # Check group exists and member not already added (via is_authorized)
    if not await _group_contains_key(group_id):
        raise Exception(f"Group {group_id} not found")
    if await _is_authorized(group_id, member_id):
        raise Exception(f"User {member_id} already a member")
    near = Account(signer, private_key, rpc)
    result = await near.function_call(
        contract_id=contract_id,
        method_name="add_group_member",
        args={"group_id": group_id, "user_id": member_id},
        amount=int("500000000000000000000")  # 0.0005 NEAR yocto
    )
    if "SuccessValue" in result.status:
        print(f"Added {member_id} to {group_id}")
        return "Added"
    raise Exception(f"Add failed: {result.status}")

@mcp.tool
async def revoke_group_member(group_id: str, member_id: str) -> str:
    """Revokes member from group (owner only, rotates key). Returns 'Revoked'."""
    contract_id = os.environ["CONTRACT_ID"]
    private_key = os.environ["NEAR_PRIVATE_KEY"]
    rpc = os.environ["RPC_URL"]
    signer = os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")  # Owner
    # Check group exists and member is authorized
    if not await _group_contains_key(group_id):
        raise Exception(f"Group {group_id} not found")
    if not await _is_authorized(group_id, member_id):
        raise Exception(f"User {member_id} not a member")
    near = Account(signer, private_key, rpc)
    result = await near.function_call(
        contract_id=contract_id,
        method_name="revoke_group_member",
        args={"group_id": group_id, "user_id": member_id},
        amount=int("500000000000000000000")  # 0.0005 NEAR yocto
    )
    if "SuccessValue" in result.status:
        print(f"Revoked {member_id} from {group_id}, key rotated")
        return "Revoked"
    raise Exception(f"Revoke failed: {result.status}")

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)