# Setup Guide

## Prerequisites

- macOS with Homebrew installed
- Python 3.11+
- Ollama with `llama3.1:8b` model
- Alpaca paper trading account
- Telegram bot token

## Installation

```bash
# Clone the repo
git clone https://github.com/VagabondCarlo/argus.git
cd argus

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill in your credentials
cp .env.example .env
```

## Configuration

Edit `.env` with your credentials. Never commit this file — it is in `.gitignore`.

## Running (Development — single machine)

```bash
# Terminal 1: Analyst agent
python -m analyst.main

# Terminal 2: Executor agent
python -m executor.main
```

## Running (Production — two Mac Minis)

Set `ANALYST_HOST` and `EXECUTOR_HOST` in `.env` to the local IP addresses of each Mac Mini.
