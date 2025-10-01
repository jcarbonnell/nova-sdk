import os
from dotenv import load_dotenv
from fastmcp import FastMCP
import base64
import requests
import time
import json
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import py_near
from py_near.account import Account
import asyncio
import hashlib
from borsh_construct import CStruct, String

# Load .env variables
load_dotenv()

mcp = FastMCP(name="nova-mcp")

# Helpers (for internal chaining)
def _encrypt_data(data: str, key: str) -> str:
    """Helper: Encrypt base64 data with AES-CBC (32-byte key). Returns b64 encrypted."""
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
    """Helper: Decrypt b64 encrypted with AES-CBC. Returns b64 decrypted."""
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

async def _ipfs_upload(data_b64: str, filename: str) -> str:
    """Helper: Upload b64 data to Pinata IPFS. Returns CID."""
    data_bytes = base64.b64decode(data_b64)
    url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
    headers = {
        "pinata_api_key": os.environ["IPFS_API_KEY"],
        "pinata_secret_api_key": os.environ["IPFS_API_SECRET"]
    }
    files = {"file": (filename, data_bytes)}
    response = requests.post(url, headers=headers, files=files, timeout=30)
    if response.status_code == 200:
        return response.json()["IpfsHash"]
    raise Exception(f"Upload failed: {response.text[:100]}")

async def _ipfs_retrieve(cid: str) -> str:
    """Helper: Retrieve from dedicated Pinata gateway. Returns b64 bytes."""
    gateway = os.environ.get("PINATA_GATEWAY", "https://gateway.pinata.cloud/ipfs").rstrip('/')
    url = f"{gateway}/ipfs/{cid.lstrip('/').strip()}"
    if not cid.startswith('Qm'):
        raise Exception(f"Invalid CID: {cid}")
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
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
    raise Exception(f"Failed after {max_retries} retries")

async def _record_near_transaction(group_id: str, user_id: str, file_hash: str, ipfs_hash: str) -> str:
    """Helper: Record tx on contract. Returns trans_id."""
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
        return result.status['SuccessValue']  # str/hex
    raise Exception(f"Record failed: {result.status}")

async def _get_group_key(group_id: str, user_id: str) -> str:
    """Helper: Borsh-serialized RPC view for key. Returns base64 key."""
    contract_id = os.environ["CONTRACT_ID"]
    rpc = os.environ["RPC_URL"]
    # Borsh args struct
    args_struct = CStruct("group_id" / String, "user_id" / String)
    # Fix: Pass dict as positional 'obj' to build
    args_obj = {"group_id": group_id, "user_id": user_id}
    args_bytes = args_struct.build(args_obj)
    args_b64 = base64.b64encode(args_bytes).decode()
    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time()),
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
    response = await asyncio.to_thread(lambda: requests.post(rpc, json=payload, headers=headers, timeout=10))
    if response.status_code == 200:
        result = response.json()
        if "error" in result:
            raise Exception(f"RPC error: {result['error']}")
        value_b64 = result['result']['result']['value']
        # Borsh result struct (SuccessValue: String)
        result_struct = CStruct("SuccessValue" / String)
        # Fix: Parse returns struct; access .SuccessValue
        parsed = result_struct.parse(base64.b64decode(value_b64))
        return parsed.SuccessValue
    raise Exception(f"View failed {response.status_code}: {response.text[:100]}")

# MCP tools use helpers
@mcp.tool
def encrypt_data(data: str, key: str) -> str:
    return _encrypt_data(data, key)

@mcp.tool
def decrypt_data(encrypted: str, key: str) -> str:
    return _decrypt_data(encrypted, key)

@mcp.tool
async def ipfs_upload(data: str, filename: str) -> str:
    return await _ipfs_upload(data, filename)

@mcp.tool
async def ipfs_retrieve(cid: str) -> str:
    return await _ipfs_retrieve(cid)

@mcp.tool
async def record_near_transaction(group_id: str, user_id: str, file_hash: str, ipfs_hash: str) -> str:
    return await _record_near_transaction(group_id, user_id, file_hash, ipfs_hash)

@mcp.tool
async def store_group_key(group_id: str, key: str) -> str:
    key_bytes = base64.b64decode(key)
    if len(key_bytes) != 32:
        raise Exception(f"Invalid key length: {len(key_bytes)}")
    contract_id = os.environ["CONTRACT_ID"]
    private_key = os.environ["NEAR_PRIVATE_KEY"]
    rpc = os.environ["RPC_URL"]
    signer = os.environ.get("SIGNER_ACCOUNT_ID", "nova-sdk-2.testnet")
    near = Account(signer, private_key, rpc)
    result = await near.function_call(
        contract_id=contract_id,
        method_name="store_group_key",
        args={"group_id": group_id, "key": key},
        amount=int("500000000000000000000")
    )
    if "SuccessValue" in result.status:
        return "Stored"
    raise Exception(f"Store failed: {result.status}")

@mcp.tool
async def get_group_key(group_id: str, user_id: str) -> str:
    return await _get_group_key(group_id, user_id)

@mcp.tool
async def composite_upload(group_id: str, user_id: str, data: str, filename: str) -> dict:
    """Full E2E: get key → encrypt → IPFS → record. Returns {'cid': str, 'trans_id': str}."""
    # Chain helpers
    key = await _get_group_key(group_id, user_id)
    encrypted_b64 = _encrypt_data(data, key)
    cid = await _ipfs_upload(encrypted_b64, filename)
    file_hash = hashlib.sha256(base64.b64decode(data)).hexdigest()
    trans_id = await _record_near_transaction(group_id, user_id, file_hash, cid)
    print(f"Composite: CID {cid}, Tx {trans_id} for {filename}")
    return {"cid": cid, "trans_id": trans_id}

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)