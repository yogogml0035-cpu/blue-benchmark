"""Run the explicit production Checkpointer schema setup."""

from app.lib.ai_runtime.checkpoint import setup_checkpointer


if __name__ == "__main__":
    setup_checkpointer()
    print("Checkpointer schema setup complete")
