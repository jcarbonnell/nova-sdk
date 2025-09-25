from nearai.agents.environment import Environment
import os
import asyncio
import hashlib
import requests
import time
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64
import py_near

def get_file_from_thread_or_local(env: Environment, extensions=(".wav", ".txt")) -> tuple:
    """Ingest file: Prefer thread, fallback to local dir scan/copy to thread."""
    start = time.time()
    # Early reply for poll
    env.add_reply("Ingesting file from thread or local dir...")
    thread_files = env.list_files_from_thread()
    if thread_files:
        file_obj = thread_files[0]
        if file_obj.filename.lower().endswith(extensions):
            env.add_reply(f"Ingested from thread: {file_obj.filename}")
            env.add_system_log(f"Thread file found: {file_obj.filename}")
            env.add_system_log(f"Ingest took {time.time() - start}s")
            return file_obj.filename, True
    # Fallback: Scan local, limit to first match
    files = [f for f in os.listdir(".") if f.lower().endswith(extensions)][:1]  # First only
    file = files[0] if files else None
    if file:
        file_path = os.path.join(".", file)
        with open(file_path, "rb") as f:
            file_data = f.read()
        if len(file_data) > 1_000_000:
            env.add_reply("File too large (>1MB); use smaller for MVP.")
            env.add_system_log(f"File {file} too large: {len(file_data)} bytes")
            env.add_system_log(f"Ingest took {time.time() - start}s")
            return None, None
        env.write_file(file, file_data)
        env.add_reply(f"Ingested from local: {file} (synced to thread)")
        env.add_system_log(f"Local file read: {file}, size: {len(file_data)} bytes")
        env.add_system_log(f"Ingest took {time.time() - start}s")
        return file, False
    env.add_reply("No .wav/.txt file in thread or local dir. Drag one or place in agent folder.")
    env.add_system_log(f"Ingest took {time.time() - start}s")
    return None, None

async def list_files(env: Environment, user_id: str, query: str):
    """List files via get_transactions_for_group view."""
    contract_id = env.env_vars.get("CONTRACT_ID", "nova-sdk-2.testnet")
    private_key = env.env_vars.get("NEAR_PRIVATE_KEY", "").replace("ed25519:", "").strip()
    if not private_key or len(private_key) < 40 or not all(c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz" for c in private_key):
        env.add_reply("Error: Invalid NEAR_PRIVATE_KEY (base58, 40+ chars, no prefix).")
        env.add_system_log("Invalid private_key for list")
        return
    near = env.set_near(user_id, private_key, rpc_addr="https://rpc.testnet.near.org")
    start = time.time()
    try:
        group_id = query.split("list files ")[1].strip() if "list files " in query else "default"
        result = await near.view(
            contract_id=contract_id,
            method_name="get_transactions_for_group",
            args={"group_id": group_id, "user_id": user_id}
        )
        transactions = result.result
        if transactions:
            reply = f"Files in {group_id}:\n"
            for tx in transactions:
                reply += f"- IPFS: {tx['ipfs_hash']}, Hash: {tx['file_hash']}\n"
            env.add_reply(reply)
        else:
            env.add_reply(f"No files in {group_id}.")
        env.add_system_log(f"List took {time.time() - start}s")
        # Optional log receipts (non-blocking)
        env.add_system_log(f"Receipts: {getattr(result, 'receipts_outcome', 'none')}")
    except Exception as e:
        env.add_reply(f"List error: {str(e)}")
        env.add_system_log(f"List failed: {str(e)}")

async def process_file(env: Environment, user_id: str, query: str):
    """Upload flow."""
    contract_id = env.env_vars.get("CONTRACT_ID", "nova-sdk-2.testnet")
    private_key = env.env_vars.get("NEAR_PRIVATE_KEY", "").replace("ed25519:", "").strip()
    if not private_key or len(private_key) < 40 or not all(c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz" for c in private_key):
        env.add_reply("Error: Invalid NEAR_PRIVATE_KEY (base58, 40+ chars, no prefix).")
        env.add_system_log("Invalid private_key for upload")
        return
    near = env.set_near(user_id, private_key, rpc_addr="https://rpc.testnet.near.org")
    start = time.time()
    try:
        group_id = "test_group"
        filename, in_thread = get_file_from_thread_or_local(env)
        if not filename:
            return
        if not in_thread:
            with open(f"./{filename}", "rb") as f:
                file_data = f.read()
            env.write_file(filename, file_data)
            env.add_system_log(f"Synced local {filename} to thread")
        else:
            file_data = env.read_file(filename)
            # Convert str to bytes if text file
            if isinstance(file_data, str):
                file_data = file_data.encode('utf-8')
                env.add_system_log(f"Converted str to bytes for {filename} (len: {len(file_data)})")
        env.add_reply("Encrypting file...")  # Early reply for poll
        # Get key
        key_result = await near.view(
            contract_id=contract_id,
            method_name="get_group_key",
            args={"group_id": group_id, "user_id": user_id}
        )
        group_key = key_result.result
        if not group_key:
            env.add_reply(f"No key for {group_id}. Run 'store group key {group_id} <base64_32byte>' via CLI.")
            return
        # Encrypt with try/except
        enc_start = time.time()
        try:
            env.add_system_log(f"Encrypt types - data: {type(file_data)} (len: {len(file_data)}), key: {type(group_key)} (len: {len(group_key)})")
            encrypted_data = encrypt_file(file_data, group_key)
            env.add_system_log(f"Encryption took {time.time() - enc_start}s")
        except Exception as enc_e:
            env.add_reply(f"Encryption failed: {str(enc_e)} (types: data={type(file_data)}, key={type(group_key)})")
            env.add_system_log(f"Encrypt error: {str(enc_e)}")
            return
        env.add_reply("Uploading to IPFS...")  # Early reply
        # Hash
        file_hash = hashlib.sha256(file_data).hexdigest()
        # Upload with type check
        ipfs_start = time.time()
        try:
            env.add_system_log(f"Upload types - filename: {type(filename)} (val: '{filename}'), data: {type(encrypted_data)} (len: {len(encrypted_data)})")
            ipfs_hash = await upload_to_ipfs(encrypted_data, str(filename), env)  # Explicit str
            env.add_system_log(f"IPFS upload took {time.time() - ipfs_start}s")
        except Exception as ipfs_e:
            env.add_reply(f"IPFS upload failed: {str(ipfs_e)}")
            env.add_system_log(f"IPFS error: {str(ipfs_e)}")
            return
        # Validate pin immediately
        val_start = time.time()
        gateway = env.env_vars.get("PINATA_GATEWAY")
        val_url = f"{gateway}{ipfs_hash}"
        val_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        val_resp = requests.head(val_url, headers=val_headers, timeout=10)
        env.add_system_log(f"Pin validation HEAD for {ipfs_hash}: status {val_resp.status_code}, len {len(val_resp.content) if val_resp.content else 0}")
        if val_resp.status_code != 200:
            raise Exception(f"Pin failed for {ipfs_hash}: {val_resp.status_code} - {val_resp.text[:100]} (check Pinata dashboard)")
        env.add_system_log(f"Pin validated: {val_resp.status_code} in {time.time() - val_start}s")
        env.add_reply("Recording transaction...")  # Early reply
        # Record
        call_start = time.time()
        result = await near.call(
            contract_id=contract_id,
            method_name="record_transaction",
            args={
                "group_id": group_id,
                "user_id": user_id,
                "file_hash": file_hash,
                "ipfs_hash": ipfs_hash
            },
            amount=2000000000000000000000  # 0.002 NEAR
        )
        env.add_system_log(f"Contract call took {time.time() - call_start}s")
        # Simple status check (mimic auth-agent)
        status = 'Success' if 'SuccessValue' in result.status else f'Failed: {result.status}'
        trans_id = str(result.result) if hasattr(result, 'result') and result.result else status
        tx_hash = result.transaction.hash if hasattr(result, 'transaction') and result.transaction else "unknown"
        explorer_link = f"https://testnet.nearblocks.io/txns/{tx_hash}"
        env.add_reply(f"✅ Uploaded {filename}: IPFS {ipfs_hash}, Tx {trans_id}. Explorer: {explorer_link}")
        env.add_system_log(f"Receipts: {getattr(result, 'receipts_outcome', 'skipped')}")
        env.add_system_log(f"Process took {time.time() - start}s")
    except Exception as e:
        env.add_reply(f"Upload error: {str(e)}")
        env.add_system_log(f"Upload failed: {str(e)}")

async def retrieve_file(env: Environment, user_id: str, query: str):
    """Retrieve/decrypt file."""
    contract_id = env.env_vars.get("CONTRACT_ID", "nova-sdk-2.testnet")
    private_key = env.env_vars.get("NEAR_PRIVATE_KEY", "").replace("ed25519:", "").strip()
    if not private_key or len(private_key) < 40 or not all(c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz" for c in private_key):
        env.add_reply("Error: Invalid NEAR_PRIVATE_KEY (base58, 40+ chars, no prefix).")
        env.add_system_log("Invalid private_key for retrieve")
        return
    near = env.set_near(user_id, private_key, rpc_addr="https://rpc.testnet.near.org")
    start = time.time()
    try:
        env.add_reply("Fetching key and file...")  # Early reply
        parts = query.split("retrieve file ")[1].strip().split()
        if len(parts) < 1:
            env.add_reply("Usage: retrieve file <ipfs_hash> [group_id]")
            return
        ipfs_hash = parts[0]
        group_id = parts[1] if len(parts) > 1 else "test_group"
        key_result = await near.view(
            contract_id=contract_id,
            method_name="get_group_key",
            args={"group_id": group_id, "user_id": user_id}
        )
        group_key = key_result.result
        env.add_reply("Decrypting...")  # Early reply
        ipfs_start = time.time()
        encrypted_data = await retrieve_from_ipfs(ipfs_hash, env)
        env.add_system_log(f"IPFS fetch took {time.time() - ipfs_start}s")
        dec_start = time.time()
        try:
            env.add_system_log(f"Decrypt types - encrypted_data: {type(encrypted_data)} (len: {len(encrypted_data)}), key: {type(group_key)}")
            decrypted_data = decrypt_file(encrypted_data, group_key)
            env.add_system_log(f"Decryption took {time.time() - dec_start}s")
        except Exception as dec_e:
            env.add_reply(f"Decryption failed: {str(dec_e)} (types: data={type(encrypted_data)}, key={type(group_key)})")
            env.add_system_log(f"Decrypt error: {str(dec_e)}")
            return
        output_filename = f"decrypted_{ipfs_hash[:8]}.txt"
        env.write_file(output_filename, decrypted_data)
        env.add_reply(f"✅ Retrieved/decrypted {ipfs_hash} from {group_id}. Download: {output_filename}")
        env.add_system_log(f"Retrieve took {time.time() - start}s")
    except Exception as e:
        env.add_reply(f"Retrieve error: {str(e)}")
        env.add_system_log(f"Retrieve failed: {str(e)}")

def encrypt_file(data: bytes, key: str) -> bytes:
    try:
        env.add_system_log(f"Encrypt input types: data={type(data)}, key={type(key)} (key len: {len(key)})")  # Note: env not param; log outside if needed
        if isinstance(data, str):  # Fallback conversion (redundant but safe)
            data = data.encode('utf-8')
        key_bytes = base64.b64decode(key)[:32]
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        pad_len = 16 - (len(data) % 16)
        padded_data = data + bytes([pad_len] * pad_len)
        encrypted = encryptor.update(padded_data) + encryptor.finalize()
        return iv + encrypted
    except Exception as e:
        raise Exception(f"Encrypt internal error: {str(e)}")

def decrypt_file(encrypted_data: bytes, key: str) -> bytes:
    try:
        key_bytes = base64.b64decode(key)[:32]
        iv = encrypted_data[:16]
        ciphertext = encrypted_data[16:]
        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()
        pad_len = decrypted_padded[-1]
        return decrypted_padded[:-pad_len]
    except Exception as e:
        raise Exception(f"Decrypt internal error: {str(e)}")

async def upload_to_ipfs(data: bytes, filename: str, env: Environment) -> str:
    start = time.time()
    try:
        env.add_system_log(f"Upload input types: filename={type(filename)} (val: '{filename}'), data={type(data)} (len: {len(data)})")
        url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
        headers = {
            "pinata_api_key": env.env_vars["IPFS_API_KEY"],
            "pinata_secret_api_key": env.env_vars["IPFS_API_SECRET"]
        }
        enc_filename = f"enc_{str(filename)}"  # Explicit str
        files = {"file": (enc_filename, data)}
        response = requests.post(url, headers=headers, files=files, timeout=10)
        env.add_system_log(f"IPFS post took {time.time() - start}s")
        if response.status_code == 200:
            return response.json()["IpfsHash"]
        raise Exception(f"Upload failed: {response.text}")
    except Exception as e:
        env.add_system_log(f"Upload internal error: {str(e)}")
        raise

async def retrieve_from_ipfs(ipfs_hash: str, env: Environment) -> bytes:
    start = time.time()
    gateway = env.env_vars.get("PINATA_GATEWAY")
    url = f"{gateway}{ipfs_hash}"
    max_retries = 3
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            env.add_system_log(f"IPFS get attempt {attempt+1} (gateway: {gateway}): status {response.status_code}, len {len(response.content) if response.content else 0}")
            if response.status_code == 200:
                if not response.content:  # Empty but 200
                    raise Exception("Fetched empty content—check pin status")
                env.add_system_log(f"Success: {len(response.content)} bytes")
                return response.content
            elif response.status_code == 400:
                raise Exception(f"Invalid CID on {gateway}: {response.text[:100]}")
            else:
                raise Exception(f"Fetch failed: {response.status_code} - {response.text[:100]}")
        except Exception as e:
            env.add_system_log(f"Attempt {attempt+1} error: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(10 * (2 ** attempt))  # Exponential backoff for 429
                continue
    raise Exception(f"Failed after {max_retries} retries on {gateway}")

async def run(env: Environment):
    prompt = {"role": "system", "content": "You are part of NOVA secure file sharing. For 'upload file', ingest from thread/local and confirm filename."}
    messages = env.list_messages()
    user_id = "nova-sdk-2.testnet"
    if not messages:
        env.add_reply("Commands:\n- upload file (after drag and drop)\n- list files <group>\n- retrieve file <hash> <group>.")
        env.request_user_input()
        return
    user_query = messages[-1]["content"].strip().lower()
    if "upload file" in user_query:
        await process_file(env, user_id, user_query)
    elif "list files" in user_query:
        await list_files(env, user_id, user_query)
    elif "retrieve file" in user_query:
        await retrieve_file(env, user_id, user_query)
    else:
        result = env.completion([prompt] + messages)
        env.add_reply(result)
    env.request_user_input()

asyncio.run(run(env))