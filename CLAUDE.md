# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run locally (dev)
uv run python main.py

# Build and run with Docker
docker compose up -d --build

# Install dependencies after pulling new code
uv pip install -e .
```

No test suite exists yet.

## Architecture

博导建联 — a web app for searching Chinese doctoral supervisor info. Users enter school + major + optional names; an LLM agent searches the web, extracts content, and returns structured results. Export to PDF or Excel.

**Stack:** NiceGUI (Python web UI on FastAPI) → DeepSeek LLM via langchain → Tavily / DuckDuckGo search + Jina AI reader for web content → ReportLab PDF / openpyxl Excel export.

**Entry point:** `main.py` loads `.env`, imports `app` (which triggers `@ui.page('/')` route registration), then starts NiceGUI on `0.0.0.0:8080`.

**Key modules:**

| Module | Role |
|---|---|
| `app.py` | Login gate, search form handler, streaming UI updates, heartbeat animation |
| `agent/supervisor.py` | Custom LLM agent loop (not LangGraph): up to 6 tool-calling turns, max 2 no-progress turns, parallel tool execution, truncated JSON recovery |
| `agent/tools.py` | 4 `@tool`s: `ddg_search`, `jina_reader`, `tavily_search`, `tavily_crawl`. Round-robin key rotation across 12 Tavily keys |
| `agent/prompts.py` | Prompt templates routed by query mode (list vs detail vs name-only vs multi-school) |
| `services/search_service.py` | Orchestrates agent calls; handles multi-school search (picks 3 schools from 985/211/双非 tiers seeded by major name hash) |
| `data/school_levels.py` | Hardcoded 985/211 school lists + alias fuzzy matching |
| `ui/components.py` | NiceGUI search form, supervisor cards, table, PDF/Excel generation with cross-platform Chinese font detection |

**Login:** username `admin`, password from `PHD_LOGIN_PASSWORD` env var.

**NiceGUI session note:** The project monkey-patches attributes (e.g., `_schools`, `_search_request`) onto objects for cross-call state — this is a NiceGUI pattern since `@ui.page` functions run fresh on each WebSocket connection but share the module namespace.
