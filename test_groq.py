import os
import json
import httpx
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
EULER_MCP_TOKEN = os.environ.get("EULER_MCP_TOKEN", "")

# Load token from file if exists
try:
    with open('.euler_token', 'r') as f:
        # just a test, actually we can just get token from euler_oauth
        pass
except:
    pass

import sys
sys.path.append(os.getcwd())
from utils.euler_oauth import get_token_set, try_load_persisted

ts = try_load_persisted()
token = ts.access_token if ts else ""

print(f"Token: {token[:10]}...")

body = {
    "model": "llama-3.3-70b-versatile",
    "input": [{"role": "user", "content": "What tools do you have?"}],
    "tools": [{
        "type": "mcp",
        "server_label": "euler",
        "server_url": "https://mcp.eulerapp.com/mcp",
        "headers": {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        },
        "server_description": "EULER Partner Data Lake",
        "require_approval": "never"
    }],
    "max_output_tokens": 100
}

with httpx.Client() as client:
    resp = client.post(
        "https://api.groq.com/openai/v1/responses",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body
    )
print(resp.status_code)
print(resp.text)
