import httpx
import os
import sys

sys.path.append(os.getcwd())
from utils.euler_oauth import get_token_set, try_load_persisted

ts = try_load_persisted()
token = ts.access_token if ts else ""

with httpx.Client() as client:
    resp = client.get(
        "https://mcp.eulerapp.com/mcp",
        headers={
            "Authorization": f"Bearer {token}", 
            "Accept": "text/event-stream"
        }
    )
print(resp.status_code)
print(resp.text)
