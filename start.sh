#!/bin/bash

# Partner Command Center Startup Script
# Launches DB-GPT via Docker + Gradio Dashboard

set -e

echo "🚀 Starting Partner Management Command Center..."

# 1. Ensure .env is loaded
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
  echo "✅ Loaded .env variables"
else
  echo "⚠️  .env file not found! Using defaults."
fi

# 2. Start DB-GPT with Docker Compose
echo "🐳 Starting DB-GPT server..."
docker compose up -d

# Wait for DB-GPT to be ready
echo "⏳ Waiting for DB-GPT to initialize (this may take 30-60 seconds)..."
for i in {1..30}; do
  if curl -s http://localhost:5670/health > /dev/null 2>&1; then
    echo "✅ DB-GPT is ready!"
    break
  fi
  sleep 2
done

# 3. Install Python dependencies if needed
echo "📦 Ensuring Python dependencies..."
pip install -r requirements.txt --quiet

# 4. Launch Gradio app
echo "🌐 Starting Gradio Dashboard on http://127.0.0.1:7860"
echo "💡 New Hybrid Tab supports Region / Tier / Source filters + RAG"
echo "Press Ctrl+C to stop everything."
python app.py
