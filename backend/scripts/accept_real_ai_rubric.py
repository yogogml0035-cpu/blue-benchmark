"""Real-AI acceptance: batch upload -> production worker -> review -> published.

Runs against an isolated SQLite business database while calling the configured
real AI provider for rubric generation. Output is limited to stage markers,
counts, ids and error codes — never material bodies.

Contract exercised: upload -> real generation (unconfirmed draft) -> publish
refused -> teacher saves final criteria -> publish -> review-reopen ->
re-publish.

Usage: uv run python -m scripts.accept_real_ai_rubric
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _configure_environment() -> Path:
    root = Path(tempfile.mkdtemp(prefix="accept-real-ai-rubric-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{root / 'business.db'}"
    os.environ["AI_RUNTIME_MODE"] = "production"
    os.environ["DATABASE_SCHEMA_CHECK_ON_STARTUP"] = "false"
    return root


def main() -> int:
    root = _configure_environment()
    from fastapi.testclient import TestClient

    from app.lib.database import clear_business_data
    from app.lib.operations.worker import production_worker
    from app.main import app
    from tests import helpers

    clear_business_data()
    print(f"ACCEPT_REAL_AI_ROOT={root}")

    with TestClient(app) as client:
        helpers.register_admin(client)
        scene = helpers.create_scene(client, name="真实AI验收场景")
        credential = helpers.create_credential(client, scene["id"])
        print(f"ACCEPT_REAL_AI_STAGE=scene scene_id={scene['id']}")

        cases = [
            helpers.make_case(
                "real-case-1",
                title="新闻稿改写",
                task_prompt="请把提供的新闻素材改写成一段正式新闻稿，保持事实准确，不要虚构。",
            ),
            helpers.make_case(
                "real-case-2",
                title="纪要整理",
                task_prompt="请把会议讨论整理成一页结构化纪要，突出结论与行动项。",
                bad_cases=[],
                memory_materials=[
                    {
                        "client_ref_id": "mem-real",
                        "source_label": "项目记忆",
                        "content_text": "纪要使用列表结构，结论放在最前面。",
                    }
                ],
            ),
        ]
        response = helpers.upload_batch(
            client, credential["token"], helpers.make_batch("accept-real-ai", cases)
        )
        if response.status_code != 201:
            print(f"ACCEPT_REAL_AI=FAIL stage=upload code={response.status_code}")
            return 1
        question_ids = [item["question_id"] for item in response.json()["cases"]]
        print(f"ACCEPT_REAL_AI_STAGE=uploaded count={len(question_ids)}")

        with production_worker() as worker:
            rounds = 0
            while worker.run_once():
                rounds += 1
                if rounds > 50:
                    print("ACCEPT_REAL_AI=FAIL stage=worker message=not-idle")
                    return 1
        print(f"ACCEPT_REAL_AI_STAGE=worker rounds={rounds}")

        for question_id in question_ids:
            detail = client.get(f"/api/questions/{question_id}").json()
            if detail["status"] != "pending_review":
                code = (detail.get("last_error") or {}).get("code", "UNKNOWN")
                print(
                    f"ACCEPT_REAL_AI=FAIL stage=generation question={question_id} "
                    f"status={detail['status']} code={code}"
                )
                return 1
            criteria = detail["criteria"] or []
            if not criteria:
                print(f"ACCEPT_REAL_AI=FAIL stage=criteria question={question_id} count=0")
                return 1
            for item in criteria:
                if set(item.keys()) != {"id", "criterion", "pass_score"}:
                    print(
                        f"ACCEPT_REAL_AI=FAIL stage=contract question={question_id} "
                        f"fields={sorted(item.keys())}"
                    )
                    return 1
            if detail["criteria_confirmed"] is not False or detail["next_action"] != "review_criteria":
                print(
                    f"ACCEPT_REAL_AI=FAIL stage=draft question={question_id} "
                    f"confirmed={detail['criteria_confirmed']} next={detail['next_action']}"
                )
                return 1
            print(
                f"ACCEPT_REAL_AI_STAGE=question question={question_id} "
                f"criteria={len(criteria)} revision={detail['content_revision']}"
            )

            # An unconfirmed AI draft must not be publishable.
            refused = client.post(
                f"/api/questions/{question_id}/publication",
                json={"command_id": f"accept-draft-{question_id}", "content_revision": detail["content_revision"]},
            )
            if refused.status_code != 409 or refused.json()["error"]["code"] != "CRITERIA_NOT_CONFIRMED":
                print(
                    f"ACCEPT_REAL_AI=FAIL stage=draft-gate question={question_id} "
                    f"code={refused.status_code}"
                )
                return 1

            # The teacher saves the final criteria list, confirming the draft.
            patched = client.patch(
                f"/api/questions/{question_id}/criteria",
                json={
                    "command_id": f"accept-confirm-{question_id}",
                    "content_revision": detail["content_revision"],
                    "criteria": criteria,
                },
            )
            if patched.status_code != 200 or patched.json()["criteria_confirmed"] is not True:
                print(
                    f"ACCEPT_REAL_AI=FAIL stage=confirm question={question_id} "
                    f"code={patched.status_code}"
                )
                return 1

            # Publish the confirmed question to exercise the full contract.
            publish = client.post(
                f"/api/questions/{question_id}/publication",
                json={"command_id": f"accept-publish-{question_id}", "content_revision": patched.json()["content_revision"]},
            )
            if publish.status_code != 200:
                print(f"ACCEPT_REAL_AI=FAIL stage=publish question={question_id} code={publish.status_code}")
                return 1

            # Reopen for review and re-publish: no version history is created.
            published = publish.json()
            reopened = client.post(
                f"/api/questions/{question_id}/review-reopen",
                json={"command_id": f"accept-reopen-{question_id}", "content_revision": published["content_revision"]},
            )
            if reopened.status_code != 200 or reopened.json()["status"] != "pending_review":
                print(
                    f"ACCEPT_REAL_AI=FAIL stage=reopen question={question_id} "
                    f"code={reopened.status_code}"
                )
                return 1
            if reopened.json()["criteria_confirmed"] is not True or not reopened.json()["criteria"]:
                print(f"ACCEPT_REAL_AI=FAIL stage=reopen-facts question={question_id}")
                return 1
            republished = client.post(
                f"/api/questions/{question_id}/publication",
                json={"command_id": f"accept-republish-{question_id}", "content_revision": reopened.json()["content_revision"]},
            )
            if republished.status_code != 200 or republished.json()["status"] != "published":
                print(
                    f"ACCEPT_REAL_AI=FAIL stage=republish question={question_id} "
                    f"code={republished.status_code}"
                )
                return 1
            print(f"ACCEPT_REAL_AI_STAGE=published question={question_id}")

        listing = client.get(
            f"/api/questions?scene_id={scene['id']}&status=published"
        ).json()
        if listing["total"] != len(question_ids):
            print(f"ACCEPT_REAL_AI=FAIL stage=library published={listing['total']}")
            return 1

    print("ACCEPT_REAL_AI=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
