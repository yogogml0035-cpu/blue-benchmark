# Production AI runtime wiring evidence

Checked on 2026-08-30 against the active `codex/production-ai-worker` checkout.

## Repository evidence

- `backend/app/lib/operations/worker.py` module entry constructs `default_worker()`; that function registers business handlers but only calls `initialize_ai_runtime()` and never installs `production_adapters(...)`.
- `backend/app/lib/ai_runtime/adapters.py` has real Deep Agents adapters and `production_adapters(checkpointer)`, but its model branch only distinguishes “AI_BASE_URL set” and always constructs Anthropic in that branch.
- The adapters use synchronous `graph.invoke()` and `graph.get_state()`.
- `backend/app/lib/ai_runtime/checkpoint.py` exposes only `open_async_postgres_checkpointer(...)`; a synchronous `PostgresSaver` is required for the current Worker call chain.
- `.env.example` has no real model Provider/key/model/base URL contract and shows a SQLAlchemy-style Checkpointer URL.
- `backend/pyproject.toml` pins `langchain-anthropic` and PostgreSQL Checkpointer packages but not `langchain-openai`.

## Framework evidence

- LangChain ChatOpenAI documentation: <https://docs.langchain.com/oss/python/integrations/chat/openai.md>
  - `ChatOpenAI` is the supported client for official OpenAI API contracts and accepts an explicit `base_url` for compatible endpoints.
  - Third-party non-standard reasoning fields are not preserved; Provider-specific packages are recommended if those fields are required.
- LangChain ChatAnthropic documentation: <https://docs.langchain.com/oss/python/integrations/chat/anthropic.md>
  - `ChatAnthropic` supports tool calling and structured output.
  - Newer Claude models may reject non-default sampling parameters, so the runtime should omit `temperature`.
- LangGraph checkpointer integrations: <https://docs.langchain.com/oss/python/integrations/checkpointers/index.md>
  - `langgraph-checkpoint-postgres` / `PostgresSaver` is the production PostgreSQL backend.
- Pinned `langgraph-checkpoint-postgres==3.1.2` source inspection shows `PostgresSaver.from_conn_string()` opens psycopg with `autocommit=True`, `prepare_threshold=0`, and `dict_row`; direct construction accepts a custom serializer, which is needed to preserve the existing AES-encrypted payload contract.

## Decision

Use two explicit protocol families only: `openai` through `ChatOpenAI`, and `anthropic` through `ChatAnthropic`. Treat vendor/model capability as an acceptance property proven by smoke, not something implied by the Provider label. Keep the synchronous Worker and introduce a synchronous encrypted saver rather than converting the entire OperationJob/Feature call chain to async.
