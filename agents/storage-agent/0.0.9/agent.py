from nearai.agents.environment import Environment
import os
import asyncio
import hashlib
import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

def get_file_from_thread_or_local(env: Environment, extensions=(".wav",)) -> tuple:
    """Ingest file: Prefer thread, fallback to local dir scan/copy to thread."""
    # Step 1: Check thread files (drag-and-drop in chat)
    thread_files = env.list_files_from_thread()
    if thread_files:
        file_obj = thread_files[0]  # Take first
        if file_obj.filename.lower().endswith(extensions):
            env.add_system_log(f"Thread file found: {file_obj.filename}")
            return file_obj.filename, True  # Already in thread

    # Step 2: Fallback to local scan (for testing; scan current dir only to start simple)
    try:
        files = os.listdir(".")
        for file in files:
            if file.lower().endswith(extensions):
                file_path = os.path.join(".", file)
                with open(file_path, "rb") as f:
                    file_data = f.read()
                preview = file_data[:10]
                env.add_system_log(f"Local file read: {file}, size: {len(file_data)} bytes, preview: {preview}")
                return file, False  # Now in thread
    except Exception as e:
        env.add_system_log(f"Local scan error: {str(e)}")

    env.add_reply("No .wav file in thread or local dir (./). Drag one or place in agent folder.")
    return None, None

async def list_files(env: Environment, user_id: str, query: str):
    """List files via get_transactions_for_group view."""
    contract_id = env.env_vars.get("CONTRACT_ID", "nova-sdk-2.testnet")
    private_key = env.env_vars.get("NEAR_PRIVATE_KEY")
    near = env.set_near(user_id, private_key, rpc_addr="https://rpc.testnet.near.org")
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
    except Exception as e:
        env.add_reply(f"List error: {str(e)}")

async def retrieve_file(env: Environment, user_id: str, query: str):
    """Retrieve/decrypt file."""
    contract_id = env.env_vars.get("CONTRACT_ID", "nova-sdk-2.testnet")
    private_key = env.env_vars.get("NEAR_PRIVATE_KEY")
    near = env.set_near(user_id, private_key, rpc_addr="https://rpc.testnet.near.org")
    try:
        parts = query.split("retrieve file ")[1].strip().split()
        if len(parts) < 1:
            env.add_reply("Usage: retrieve file <ipfs_hash> [group_id]")
            return
        ipfs_hash = parts[0]
        group_id = parts[1] if len(parts) > 1 else "default"
        # Get key (view)
        key_result = await near.view(
            contract_id=contract_id,
            method_name="get_group_key",
            args={"group_id": group_id}
        )
        group_key = key_result.result
        # Fetch from IPFS
        encrypted_data = await retrieve_from_ipfs(ipfs_hash, env)  # Define func below
        # Decrypt
        decrypted_data = decrypt_file(encrypted_data, group_key)  # Define below
        # Write to thread
        output_filename = f"decrypted_{ipfs_hash[:8]}.txt"  # Adapt ext
        env.write_file(output_filename, decrypted_data)
        env.add_reply(f"✅ Retrieved/decrypted {ipfs_hash} from {group_id}. Download: {output_filename}")
    except Exception as e:
        env.add_reply(f"Retrieve error: {str(e)}")

def decrypt_file(encrypted_data: bytes, key: str) -> bytes:
    """AES-CBC decrypt (adapt from your simple version; use cryptography)."""
    from base64 import b64decode
    key_bytes = b64decode(key)[:32]  # 32-byte key
    iv = encrypted_data[:16]
    ciphertext = encrypted_data[16:]
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()
    # Simple unpad
    return decrypted_padded.rstrip(b'\0')

async def retrieve_from_ipfs(ipfs_hash: str, env: Environment) -> bytes:
    """Fetch from Pinata gateway."""
    url = f"https://gateway.pinata.cloud/ipfs/{ipfs_hash}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.content
    raise Exception(f"IPFS fetch failed: {response.status_code}")

async def run(env: Environment):
    prompt = {"role": "system", "content": "You are part of NOVA secure file sharing. For 'upload file', ingest from thread/local and confirm filename."}
    messages = env.list_messages()
    if not messages:
        env.add_reply("Type 'upload file' or 'list files <group_id>'.")
        env.request_user_input()
        return
    user_query = messages[-1]["content"].strip().lower()
    user_id = "nova-sdk-2.testnet"  # Hardcoded for MVP
    if "upload file" in user_query:
        filename, _ = get_file_from_thread_or_local(env)
        if filename:
            env.add_reply(f"✅ Ingested file: {filename} (ready for processing).")
        env.request_user_input()
        return
    elif "list files" in user_query:
        await list_files(env, user_id, user_query)
        env.request_user_input()
        return
    elif "retrieve file" in user_query:
        await retrieve_file(env, user_id, user_query)
        env.request_user_input()
        return
    
    # Fallback (boilerplate)
    result = env.completion([prompt] + messages)
    env.add_reply(result)
    env.request_user_input()

# Run async (match auth-agent)
asyncio.run(run(env))