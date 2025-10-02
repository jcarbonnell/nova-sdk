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

# Load .env variables
load_dotenv()

mcp = FastMCP(name="nova-mcp")

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
def get_group_key(group_id: str, user_id: str) -> str:  # Sync for simplicity (views are fast)
    """Retrieves group key if authorized. Returns base64 key."""
    contract_id = os.environ["CONTRACT_ID"]
    rpc_url = os.environ["RPC_URL"]
    try:
        args = {"group_id": group_id, "user_id": user_id}
        args_json = json.dumps(args)
        args_b64 = base64.b64encode(args_json.encode('utf-8')).decode('utf-8')
        print(f"Debug: Args JSON: {args_json}, B64: {args_b64[:50]}...")  # Log payload

        payload = {
            "jsonrpc": "2.0",
            "id": "get_key_call",
            "method": "query",
            "params": {
                "request_type": "call_function",
                "final": True,
                "account_id": contract_id,
                "method_name": "get_group_key",
                "args_base64": args_b64
            }
        }
        headers = {'Content-Type': 'application/json'}
        print(f"Debug: RPC URL: {rpc_url}, Payload: {json.dumps(payload)}")  # Full payload log

        response = requests.post(rpc_url, json=payload, headers=headers, timeout=5)
        print(f"Debug: RPC Status: {response.status_code}, Text: {response.text[:200]}...")  # Response snippet

        response.raise_for_status()
        result = response.json()
        print(f"Debug: Parsed JSON: {json.dumps(result, indent=2)[:300]}...")  # Full parse log

        if "error" in result:
            error_msg = result["error"].get("msg", "Unknown RPC error")
            print(f"Debug: RPC Error: {error_msg}")
            return f"Error: {error_msg}"
        key = result["result"]["result"]
        if not key:
            return "Error: No key set"
        print(f"Debug: Retrieved key: {key[:10]}...")
        return key
    except requests.exceptions.Timeout:
        print("Debug: RPC timeout")
        return "Error: RPC timeout"
    except json.JSONDecodeError as e:
        print(f"Debug: JSON decode error: {str(e)}")
        return f"Error: Invalid RPC response - {str(e)}"
    except Exception as e:
        print(f"Debug: General error: {str(e)}")
        return f"Error: {str(e)}"

@mcp.tool
async def auth_status(user_id: str, group_id: str = None) -> str:
    """Tool: Check user auth for group(s). Returns JSON {'authorized': bool, 'groups': list[str]}."""
    contract_id = os.environ["CONTRACT_ID"]
    rpc = os.environ["RPC_URL"]
    try:
        authorized = False
        groups = []
        if group_id:
            account = Account(user_id, "ed25519:dummy_view_only", rpc)
            result = account.view(  # Sync view
                contract_id=contract_id,
                method_name="is_authorized",
                args={"group_id": group_id, "user_id": user_id}
            )
            authorized = result == "true"
        else:
            account = Account(user_id, "ed25519:dummy_view_only", rpc)
            tx_result = account.view(
                contract_id=contract_id,
                method_name="get_transactions_for_group",
                args={"group_id": "default", "user_id": user_id}
            )
            authorized = len(tx_result) > 0
            groups = ["default"] if authorized else []
        result_dict = {"authorized": authorized, "groups": groups}
        print(f"Auth for {user_id}/{group_id or 'all'}: {result_dict}")
        return json.dumps(result_dict)  # JSON str for structuredContent
    except Exception as e:
        error_dict = {"error": str(e), "authorized": False, "groups": []}
        print(f"Auth error: {e}")
        return json.dumps(error_dict)

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)