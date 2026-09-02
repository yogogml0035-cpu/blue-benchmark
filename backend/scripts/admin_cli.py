"""Administrator CLI for the no-frontend phase.

Covers scene creation and scene-credential lifecycle (issue / rotate / revoke /
status) by calling the service layer directly against the business database.

Plaintext credential tokens are printed exactly once, at issue/rotate time.
Status and list commands never return plaintext tokens.

Usage:
    uv run python -m scripts.admin_cli scenes create --name "媒体场景" [--description ...]
    uv run python -m scripts.admin_cli scenes list
    uv run python -m scripts.admin_cli scenes status --scene-id <id>
    uv run python -m scripts.admin_cli credentials issue --scene-id <id> [--label ...]
    uv run python -m scripts.admin_cli credentials rotate --scene-id <id> [--label ...]
    uv run python -m scripts.admin_cli credentials revoke --scene-id <id> --credential-id <id>

Or through the Makefile:
    make admin ARGS="scenes list"
"""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.features.scenes import service as scene_service
from app.features.scenes.schemas import SceneCreateRequest
from app.lib.errors import AppError


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _fail(message: str, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def _run(action) -> None:
    try:
        action()
    except AppError as exc:
        _fail(f"[{exc.code}] {exc.message}")
    except ValidationError as exc:
        # Render field messages only; never echo input values.
        parts = "; ".join(
            f"{'.'.join(str(p) for p in err.get('loc', []))}: {err.get('msg', '')}"
            for err in exc.errors()
        )
        _fail(f"[VALIDATION_ERROR] {parts}")
    except OperationalError:
        _fail(
            "database unavailable or not migrated; run `make db-migrate` first "
            "and check DATABASE_URL."
        )
    except SQLAlchemyError as exc:
        _fail(f"[DATABASE_ERROR] {type(exc).__name__}")
    except Exception as exc:  # pragma: no cover - last-resort guard, no traceback
        _fail(f"[INTERNAL_ERROR] {type(exc).__name__}")


def _scenes_create(args: argparse.Namespace) -> None:
    view = scene_service.create_scene(
        SceneCreateRequest(name=args.name, description=args.description)
    )
    _print_json(view.model_dump())


def _scenes_list(_args: argparse.Namespace) -> None:
    response = scene_service.list_scenes()
    _print_json({"items": [item.model_dump() for item in response.items]})


def _scenes_status(args: argparse.Namespace) -> None:
    response = scene_service.get_scene_or_404(args.scene_id)
    _print_json(response.model_dump())


def _credentials_issue(args: argparse.Namespace) -> None:
    issued = scene_service.issue_credential(args.scene_id, args.label)
    _print_json(issued.model_dump())
    print(
        "\nwarning: the token above is shown only once and is not stored in "
        "plaintext. Save it now (e.g. into the Skill's private config).",
        file=sys.stderr,
    )


def _credentials_rotate(args: argparse.Namespace) -> None:
    issued = scene_service.rotate_credentials(args.scene_id, args.label)
    _print_json(issued.model_dump())
    print(
        "\nwarning: all previous active credentials were revoked. The new token "
        "is shown only once.",
        file=sys.stderr,
    )


def _credentials_revoke(args: argparse.Namespace) -> None:
    status = scene_service.revoke_credential(args.scene_id, args.credential_id)
    _print_json(status.model_dump())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="admin_cli", description="Administrator CLI for scenes and credentials."
    )
    sub = parser.add_subparsers(dest="resource", required=True)

    scenes = sub.add_parser("scenes", help="Manage scene folders.")
    scenes_sub = scenes.add_subparsers(dest="action", required=True)

    scenes_create = scenes_sub.add_parser("create", help="Create a scene folder.")
    scenes_create.add_argument("--name", required=True)
    scenes_create.add_argument("--description", default=None)
    scenes_create.set_defaults(func=_scenes_create)

    scenes_list = scenes_sub.add_parser("list", help="List scenes.")
    scenes_list.set_defaults(func=_scenes_list)

    scenes_status = scenes_sub.add_parser("status", help="Scene status (no plaintext).")
    scenes_status.add_argument("--scene-id", required=True)
    scenes_status.set_defaults(func=_scenes_status)

    credentials = sub.add_parser("credentials", help="Manage scene upload credentials.")
    credentials_sub = credentials.add_subparsers(dest="action", required=True)

    cred_issue = credentials_sub.add_parser("issue", help="Issue a credential (token shown once).")
    cred_issue.add_argument("--scene-id", required=True)
    cred_issue.add_argument("--label", default=None)
    cred_issue.set_defaults(func=_credentials_issue)

    cred_rotate = credentials_sub.add_parser(
        "rotate", help="Revoke active credentials and issue a replacement (token shown once)."
    )
    cred_rotate.add_argument("--scene-id", required=True)
    cred_rotate.add_argument("--label", default=None)
    cred_rotate.set_defaults(func=_credentials_rotate)

    cred_revoke = credentials_sub.add_parser("revoke", help="Revoke one credential.")
    cred_revoke.add_argument("--scene-id", required=True)
    cred_revoke.add_argument("--credential-id", required=True)
    cred_revoke.set_defaults(func=_credentials_revoke)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _run(lambda: args.func(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
