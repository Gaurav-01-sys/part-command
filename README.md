# Partner Management Command Center
### Linear RAG + Claude (+ optional EULER live data) + Markdown Table Context

A unified partner analytics app across:
**Microsoft** · **Snowflake** · **dbt** · **Databricks** · **Coalesce** · **AI Query**

## Quick Start

```powershell
pip install -r requirements.txt

# Copy .env.example to .env and fill in ANTHROPIC_API_KEY at minimum
Copy-Item .env.example .env

# Load `.env` into the current PowerShell session
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)\s*=\s*(.*)\s*$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
    }
}

python app.py
```

On macOS/Linux:
```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in ANTHROPIC_API_KEY at minimum
export $(grep -v '^#' .env | xargs)
python app.py
```

Open the Gradio app at `http://localhost:7860`.

## LLM Backend

The app uses Claude for the AI query tab. Set:

```env
ANTHROPIC_API_KEY=your-anthropic-api-key
CLAUDE_MODEL=claude-sonnet-5
```

### Optional: live EULER data

The application is live-only: it does not ship or fall back to local sample, synthetic, or mock records.
Both integrations are optional, and the UI reports clearly when EULER is not connected:

- **EULER_MCP_TOKEN** - gives Claude direct tool access (via Anthropic's MCP connector) to EULER's live Partner Data Lake tools during Q&A.
- **EULER_API_KEY** - pulls live partners/deals/certifications data into the dashboard via REST.

See `utils/claude_llm.py` and `utils/euler_api.py` for setup notes on each.

## What Changed

- The old DB-GPT compose wiring is removed.
- The AI query path now uses the linear RAG retriever only.
- Table previews are converted to markdown with `markitdown` when available.
- Dash and Gradio both show visible loading state while the model is responding.

## Run the Dash App

```powershell
python dash_app.py
```

Dash prints a local URL and, if `pyngrok` is installed, a shareable public link.

## Mini Anvil Alternative

`mini_anvil_demo.py` provides a small Anvil-style UI built on top of the local Gradio runtime.

```powershell
python mini_anvil_demo.py
```

To create a shareable link:

```powershell
$env:MINI_ANVIL_SHARE="1"
python mini_anvil_demo.py
```

## Architecture

```text
app.py                Gradio dashboard
dash_app.py           Dash dashboard
mini_anvil_demo.py    Small Anvil-style launcher
utils/linear_query_engine.py   NVIDIA-backed answer engine
utils/linear_rag_engine.py     Markdown retrieval over CSV tables
utils/tablerag_engine.py       Compatibility wrapper for older imports
partner_solutions/             Live partner-solution boundaries (EULER is active)
```

## Notes

- `docker-compose.yml` is intentionally empty now.
- The AI query tab is designed for conversational retrieval over live EULER MCP tools.
- If EULER is unavailable, the app returns an honest capability message and does not invent rows.
