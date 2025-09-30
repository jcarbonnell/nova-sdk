import os
from dotenv import load_dotenv
from fastmcp import FastMCP
import base64
import requests

# Load .env variables
load_dotenv()

mcp = FastMCP(name="nova-mcp")

@mcp.tool
def ipfs_upload(data: bytes, filename: str) -> str:
    """Uploads encrypted data to IPFS via Pinata and returns CID."""
    # Decode base64 data to bytes
    data_bytes = base64.b64decode(data)
    url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
    headers = {
        "pinata_api_key": os.environ["IPFS_API_KEY"],  # Use env vars
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
    import requests
    import base64
    import time
    gateway = os.environ.get("PINATA_GATEWAY", "https://gateway.pinata.cloud/ipfs").rstrip('/')
    url = f"{gateway}/{cid.lstrip('/').strip()}"  # Normalize path
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

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)