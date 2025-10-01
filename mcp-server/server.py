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
def record_near_transaction(group_id: str, user_id: str, file_hash: str, ipfs_hash: str) -> str:
    """Records file tx on NOVA contract, returns trans_id."""
    contract_id = os.environ["CONTRACT_ID"]
    private_key = os.environ["NEAR_PRIVATE_KEY"]
    rpc = os.environ["RPC_URL"]
    near = Account(user_id, private_key, rpc)
    result = near.call(
        contract_id=contract_id,
        method_name="record_transaction",
        args={"group_id": group_id, "user_id": user_id, "file_hash": file_hash, "ipfs_hash": ipfs_hash},
        attached_deposit=2000000000000000000000  # 0.002 NEAR yocto
    )
    if "SuccessValue" in result.status:
        return str(result.result)  # trans_id
    raise Exception(f"Record failed: {result.status}")

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)