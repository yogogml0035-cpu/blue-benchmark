"""Run the explicit production Checkpointer schema setup."""

import sys

from app.lib.ai_runtime.checkpoint import CheckpointError, setup_checkpointer


if __name__ == "__main__":
    try:
        setup_checkpointer()
    except CheckpointError as exc:
        print(f"Checkpointer setup failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    print("Checkpointer schema setup complete")
