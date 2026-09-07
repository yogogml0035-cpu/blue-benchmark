/* eslint-disable */
// Generated from backend/openapi.json via `pnpm generate:api`. Do not edit.
export interface paths {
    "/healthz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Healthz */
        get: operations["healthz_healthz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login */
        post: operations["login_api_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Logout */
        post: operations["logout_api_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Me */
        get: operations["me_api_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scenes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Scenes */
        get: operations["list_scenes_api_scenes_get"];
        put?: never;
        /** Create Scene */
        post: operations["create_scene_api_scenes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scenes/{scene_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Scene Status */
        get: operations["get_scene_status_api_scenes__scene_id__get"];
        put?: never;
        post?: never;
        /** Delete Scene */
        delete: operations["delete_scene_api_scenes__scene_id__delete"];
        options?: never;
        head?: never;
        /** Update Scene */
        patch: operations["update_scene_api_scenes__scene_id__patch"];
        trace?: never;
    };
    "/api/scenes/{scene_id}/credentials": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Or Replace Credential */
        post: operations["create_or_replace_credential_api_scenes__scene_id__credentials_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scenes/{scene_id}/credential": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reveal Credential */
        get: operations["reveal_credential_api_scenes__scene_id__credential_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scenes/{scene_id}/credentials/{credential_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Revoke Credential */
        delete: operations["revoke_credential_api_scenes__scene_id__credentials__credential_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/questions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Library */
        get: operations["list_library_api_questions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/questions/{question_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Question */
        get: operations["get_question_api_questions__question_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Question
         * @description Accept a protected deletion: freeze + durable cross-store cleanup.
         *
         *     202 means ACCEPTED, not deleted. Completion is only observable through
         *     the cleanup operation state (detail projection / event stream); the old
         *     "204 = row deleted = success" early-exit semantics are removed.
         */
        delete: operations["delete_question_api_questions__question_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/questions/{question_id}/title": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Title */
        patch: operations["update_title_api_questions__question_id__title_patch"];
        trace?: never;
    };
    "/api/questions/{question_id}/materials": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Materials */
        patch: operations["update_materials_api_questions__question_id__materials_patch"];
        trace?: never;
    };
    "/api/questions/{question_id}/criteria/{criterion_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Patch Criterion */
        patch: operations["patch_criterion_api_questions__question_id__criteria__criterion_id__patch"];
        trace?: never;
    };
    "/api/questions/{question_id}/regenerate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Regenerate Question */
        post: operations["regenerate_question_api_questions__question_id__regenerate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/questions/{question_id}/criteria": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Patch Criteria */
        patch: operations["patch_criteria_api_questions__question_id__criteria_patch"];
        trace?: never;
    };
    "/api/questions/{question_id}/generation-retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retry Generation */
        post: operations["retry_generation_api_questions__question_id__generation_retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/questions/{question_id}/publication": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Publish */
        post: operations["publish_api_questions__question_id__publication_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/questions/{question_id}/review-reopen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Review Reopen */
        post: operations["review_reopen_api_questions__question_id__review_reopen_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/questions/{question_id}/runs/{operation_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Run Events
         * @description One page of the complete public event log (snapshot + cursor restore).
         */
        get: operations["get_run_events_api_questions__question_id__runs__operation_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/questions/{question_id}/runs/{operation_id}/events/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Stream Run Events
         * @description Same-origin SSE over the persisted event log.
         *
         *     The stream READS the database (events are persisted before they are sent),
         *     so it never owns, starts or restarts the job: disconnects, refreshes and
         *     late subscribers only move the read cursor. Terminal conditions: question
         *     leaves ``generating`` (done), deletion freeze (frozen), superseded
         *     operation (superseded), or missing question (gone).
         */
        get: operations["stream_run_events_api_questions__question_id__runs__operation_id__events_stream_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/external/connection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Connection Status */
        get: operations["get_connection_status_api_external_connection_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/external/question-batches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Upload Question Batch */
        post: operations["upload_question_batch_api_external_question_batches_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * BadCaseIn
         * @description A rejected real result with the teacher feedback bound to it.
         */
        BadCaseIn: {
            /** Content Text */
            content_text: string;
            /** Teacher Feedback Texts */
            teacher_feedback_texts: string[];
            /** Reason Summary */
            reason_summary?: string | null;
        };
        /** BadCaseView */
        BadCaseView: {
            /** Content Text */
            content_text: string;
            /** Teacher Feedback Texts */
            teacher_feedback_texts: string[];
            /** Reason Summary */
            reason_summary: string | null;
        };
        /** BasisClaimIn */
        BasisClaimIn: {
            /** Claim */
            claim: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "teacher_explicit" | "ai_inferred";
            citation?: components["schemas"]["SourceCitationIn"] | null;
        };
        /** BasisClaimView */
        BasisClaimView: {
            /** Claim */
            claim: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "teacher_explicit" | "ai_inferred";
            citation: components["schemas"]["SourceCitationView"] | null;
        };
        /** BatchUploadRequest */
        BatchUploadRequest: {
            /**
             * Schema Version
             * @default 1.0
             * @constant
             */
            schema_version: "1.0";
            /** Command Id */
            command_id: string;
            /** Cases */
            cases?: components["schemas"]["CaseIn"][];
        };
        /** BatchUploadResponse */
        BatchUploadResponse: {
            /** Command Id */
            command_id: string;
            /** Scene Id */
            scene_id: string;
            /** Accepted Case Count */
            accepted_case_count: number;
            /** Cases */
            cases: components["schemas"]["CaseReceipt"][];
        };
        /**
         * CaseIn
         * @description One evaluation question payload inside a batch upload command.
         */
        CaseIn: {
            /** Client Case Id */
            client_case_id: string;
            /** Title */
            title: string;
            /** Task Prompt */
            task_prompt: string;
            /** Reference Examples */
            reference_examples?: components["schemas"]["ReferenceExampleIn"][];
            /** Bad Cases */
            bad_cases?: components["schemas"]["BadCaseIn"][];
            /** Reference Answer */
            reference_answer: string;
            /** Memory Materials */
            memory_materials?: components["schemas"]["MemoryMaterialIn"][];
        };
        /** CaseReceipt */
        CaseReceipt: {
            /** Client Case Id */
            client_case_id: string;
            /** Question Id */
            question_id: string;
            status: components["schemas"]["QuestionStatus"];
        };
        /** CriteriaPatchRequest */
        CriteriaPatchRequest: {
            /** Command Id */
            command_id: string;
            /** Content Revision */
            content_revision: number;
            /** Criteria */
            criteria: components["schemas"]["CriterionIn"][];
        };
        /** CriterionBasisIn */
        CriterionBasisIn: {
            /** Explanation */
            explanation: string;
            /** Claims */
            claims: components["schemas"]["BasisClaimIn"][];
        };
        /** CriterionBasisView */
        CriterionBasisView: {
            /** Explanation */
            explanation: string;
            /** Claims */
            claims: components["schemas"]["BasisClaimView"][];
        };
        /**
         * CriterionIn
         * @description Administrator-supplied criterion; identical shape to the AI output contract.
         *
         *     Teacher-edit semantics (deliberately weaker than the GENERATION contract):
         *     ``pass_score`` accepts ANY integer 0-10 — anchors are explanatory, never a
         *     whitelist; ``score_anchors`` may be empty or omit ``pass_score``; the two
         *     bases may be ``None`` for manually created criteria (explicitly empty
         *     auxiliary content, not a missing-field fallback). Editing the score does
         *     NOT rewrite or auto-fill anchors/bases; the UI flags a stale
         *     ``explained_score`` for the teacher to review.
         */
        CriterionIn: {
            /** Id */
            id: string;
            /** Criterion */
            criterion: string;
            /** Pass Score */
            pass_score: number;
            /** Score Anchors */
            score_anchors?: components["schemas"]["ScoreAnchorIn"][];
            criterion_basis?: components["schemas"]["CriterionBasisIn"] | null;
            pass_score_basis?: components["schemas"]["PassScoreBasisIn"] | null;
        };
        /**
         * CriterionPatchRequest
         * @description Field-level criterion autosave; absent fields keep their values.
         *
         *     Selection flags, confirmation state and the unselected candidate pool are
         *     never touched here; the supplied fields are re-validated through the same
         *     ``CriterionIn`` contract the explicit criteria save uses. Stored basis
         *     citations are NOT re-validated against materials on this path — staleness
         *     surfaces as the soft ``criteria_basis_stale`` reminder instead.
         */
        CriterionPatchRequest: {
            /** Content Revision */
            content_revision: number;
            /** Criterion */
            criterion?: string | null;
            /** Pass Score */
            pass_score?: number | null;
            /** Score Anchors */
            score_anchors?: components["schemas"]["ScoreAnchorIn"][] | null;
        };
        /** CriterionView */
        CriterionView: {
            /** Id */
            id: string;
            /** Criterion */
            criterion: string;
            /** Pass Score */
            pass_score: number;
            /** Score Anchors */
            score_anchors: components["schemas"]["ScoreAnchorView"][];
            criterion_basis: components["schemas"]["CriterionBasisView"] | null;
            pass_score_basis: components["schemas"]["PassScoreBasisView"] | null;
        };
        /** DeleteAcceptedResponse */
        DeleteAcceptedResponse: {
            /** Question Id */
            question_id: string;
            status: components["schemas"]["QuestionStatus"];
            /** Operation Id */
            operation_id: string;
        };
        /**
         * DeleteStateView
         * @description Projection of the accepted deletion operation (no material content).
         */
        DeleteStateView: {
            /** Operation Id */
            operation_id: string;
            /**
             * Phase
             * @enum {string}
             */
            phase: "queued" | "running" | "succeeded" | "failed";
            error?: components["schemas"]["GenerationErrorView"] | null;
        };
        /** ErrorPayload */
        ErrorPayload: {
            /** Code */
            code: string;
            /** Message */
            message: string;
            /** Details */
            details?: {
                [key: string]: unknown;
            } | null;
        };
        /** ErrorResponse */
        ErrorResponse: {
            error: components["schemas"]["ErrorPayload"];
        };
        /** GenerationErrorView */
        GenerationErrorView: {
            /** Code */
            code: string;
            /** Message */
            message: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HealthResponse */
        HealthResponse: {
            /**
             * Status
             * @default ok
             */
            status: string;
            /** Service */
            service: string;
            /**
             * Persistence
             * @default business database
             */
            persistence: string;
            /** Ai */
            ai: string;
        };
        /** LoginRequest */
        LoginRequest: {
            /** Identifier */
            identifier: string;
            /** Password */
            password: string;
        };
        /**
         * MemoryMaterialIn
         * @description Raw memory fragment the local Agent loaded this round and deemed relevant.
         */
        MemoryMaterialIn: {
            /** Client Ref Id */
            client_ref_id: string;
            /** Source Label */
            source_label?: string | null;
            /** Content Text */
            content_text: string;
        };
        /** MemoryMaterialView */
        MemoryMaterialView: {
            /** Client Ref Id */
            client_ref_id: string;
            /** Source Label */
            source_label: string | null;
            /** Content Text */
            content_text: string;
        };
        /**
         * NextAction
         * @enum {string}
         */
        NextAction: "wait_for_generation" | "retry_generation" | "review_criteria" | "publish" | "published" | "wait_for_deletion";
        /** OperationAcceptedResponse */
        OperationAcceptedResponse: {
            /** Question Id */
            question_id: string;
            status: components["schemas"]["QuestionStatus"];
            /** Operation Id */
            operation_id: string | null;
        };
        /** PassScoreBasisIn */
        PassScoreBasisIn: {
            /** Explained Score */
            explained_score: number;
            /** Explanation */
            explanation: string;
            /** Claims */
            claims: components["schemas"]["BasisClaimIn"][];
        };
        /** PassScoreBasisView */
        PassScoreBasisView: {
            /** Explained Score */
            explained_score: number;
            /** Explanation */
            explanation: string;
            /** Claims */
            claims: components["schemas"]["BasisClaimView"][];
        };
        /** QuestionCommandRequest */
        QuestionCommandRequest: {
            /** Command Id */
            command_id: string;
            /** Content Revision */
            content_revision: number;
        };
        /**
         * QuestionDeleteRequest
         * @description Protected delete-acceptance contract.
         *
         *     ``confirmation_title`` is only required for questions that were ever
         *     published; it must match the current title exactly (after Unicode NFC
         *     normalization and trimming) or the delete is rejected. Acceptance starts
         *     a durable cleanup operation; success is only reported after every
         *     cross-store trace of the question is gone.
         */
        QuestionDeleteRequest: {
            /** Command Id */
            command_id: string;
            /** Content Revision */
            content_revision: number;
            /** Confirmation Title */
            confirmation_title?: string | null;
        };
        /** QuestionDetailResponse */
        QuestionDetailResponse: {
            /** Id */
            id: string;
            /** Scene Id */
            scene_id: string;
            /** Scene Name */
            scene_name: string;
            /** Client Case Id */
            client_case_id: string;
            /** Title */
            title: string;
            /** Task Prompt */
            task_prompt: string;
            /** Reference Examples */
            reference_examples: components["schemas"]["ReferenceExampleView"][];
            /** Bad Cases */
            bad_cases: components["schemas"]["BadCaseView"][];
            /** Reference Answer */
            reference_answer: string;
            /** Memory Materials */
            memory_materials: components["schemas"]["MemoryMaterialView"][];
            /** Criteria */
            criteria: components["schemas"]["CriterionView"][] | null;
            /** Criteria Confirmed */
            criteria_confirmed: boolean;
            /** Criteria Basis Stale */
            criteria_basis_stale: boolean;
            status: components["schemas"]["QuestionStatus"];
            next_action: components["schemas"]["NextAction"];
            /** Content Revision */
            content_revision: number;
            /** Active Operation Id */
            active_operation_id: string | null;
            /** Last Operation Id */
            last_operation_id: string | null;
            last_error: components["schemas"]["GenerationErrorView"] | null;
            deletion: components["schemas"]["DeleteStateView"] | null;
            /** Delete Confirmation Required */
            delete_confirmation_required: boolean;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
            /** Published At */
            published_at: string | null;
        };
        /** QuestionLibraryResponse */
        QuestionLibraryResponse: {
            /** Items */
            items: components["schemas"]["QuestionListItem"][];
            /** Total */
            total: number;
        };
        /** QuestionListItem */
        QuestionListItem: {
            /** Id */
            id: string;
            /** Scene Id */
            scene_id: string;
            /** Scene Name */
            scene_name: string;
            /** Client Case Id */
            client_case_id: string;
            /** Title */
            title: string;
            status: components["schemas"]["QuestionStatus"];
            /** Rubric Criterion Count */
            rubric_criterion_count: number | null;
            /** Criteria Confirmed */
            criteria_confirmed: boolean;
            next_action: components["schemas"]["NextAction"];
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
            /** Published At */
            published_at: string | null;
        };
        /**
         * QuestionMaterialsPatchRequest
         * @description Partial material autosave; absent fields keep their current values.
         *
         *     Writes text only: never bumps ``content_revision``, never touches
         *     criteria, never enqueues generation. Lists are replaced wholesale when
         *     provided (item shapes reuse the batch-intake models, so validation and
         *     ``client_ref_id`` uniqueness come for free).
         */
        QuestionMaterialsPatchRequest: {
            /** Content Revision */
            content_revision: number;
            /** Task Prompt */
            task_prompt?: string | null;
            /** Reference Answer */
            reference_answer?: string | null;
            /** Reference Examples */
            reference_examples?: components["schemas"]["ReferenceExampleIn"][] | null;
            /** Bad Cases */
            bad_cases?: components["schemas"]["BadCaseIn"][] | null;
            /** Memory Materials */
            memory_materials?: components["schemas"]["MemoryMaterialIn"][] | null;
        };
        /**
         * QuestionStatus
         * @enum {string}
         */
        QuestionStatus: "generating" | "pending_review" | "generation_failed" | "published" | "deleting";
        /** QuestionTitleRequest */
        QuestionTitleRequest: {
            /** Command Id */
            command_id: string;
            /** Content Revision */
            content_revision: number;
            /** Title */
            title: string;
        };
        /**
         * ReferenceExampleIn
         * @description Teacher-provided content the local Agent actually read, then distilled.
         */
        ReferenceExampleIn: {
            /** Client Ref Id */
            client_ref_id: string;
            /** Source Name */
            source_name?: string | null;
            /** Content Text */
            content_text: string;
        };
        /** ReferenceExampleView */
        ReferenceExampleView: {
            /** Client Ref Id */
            client_ref_id: string;
            /** Source Name */
            source_name: string | null;
            /** Content Text */
            content_text: string;
        };
        /**
         * RunEventView
         * @description One persisted public progress event of a generation operation.
         */
        RunEventView: {
            /** Sequence */
            sequence: number;
            /**
             * Kind
             * @enum {string}
             */
            kind: "run_started" | "run_resumed" | "stage" | "message_delta" | "message" | "tool_started" | "tool_finished" | "tool_failed" | "interrupted" | "run_completed" | "run_failed";
            /** Stage */
            stage?: string | null;
            /** Text */
            text?: string | null;
            /** Tool */
            tool?: string | null;
            /** Detail */
            detail?: string | null;
            /** Attempt */
            attempt: number;
            /** Created At */
            created_at: string;
        };
        /** RunEventsResponse */
        RunEventsResponse: {
            /** Question Id */
            question_id: string;
            /** Operation Id */
            operation_id: string | null;
            status: components["schemas"]["QuestionStatus"];
            /** Events */
            events: components["schemas"]["RunEventView"][];
            /** Last Sequence */
            last_sequence: number;
        };
        /**
         * SceneConnectionStatusView
         * @description What a scene credential holder may learn about its own connection.
         *
         *     Never includes the token, token hash, or any other scene's data.
         */
        SceneConnectionStatusView: {
            /**
             * Status
             * @constant
             */
            status: "connected";
            /** Scene Id */
            scene_id: string;
            /** Scene Name */
            scene_name: string;
            /** Credential Id */
            credential_id: string;
            /** Last Used At */
            last_used_at: string | null;
        };
        /** SceneCreateRequest */
        SceneCreateRequest: {
            /** Name */
            name: string;
            /** Description */
            description?: string | null;
        };
        /**
         * SceneCredentialIssuedView
         * @description Returned once at create/replace time for the handoff convenience.
         *
         *     Unlike the old model, the plaintext is also persisted so the administrator
         *     can reveal it later from the scene page.
         */
        SceneCredentialIssuedView: {
            /** Credential Id */
            credential_id: string;
            /** Scene Id */
            scene_id: string;
            /** Token */
            token: string;
            /** Created At */
            created_at: string;
        };
        /**
         * SceneCredentialPlaintextView
         * @description Administrator-only reveal of the scene's current credential.
         *
         *     Served with ``Cache-Control: no-store``; never part of a listing or status
         *     response.
         */
        SceneCredentialPlaintextView: {
            /** Credential Id */
            credential_id: string;
            /** Token */
            token: string;
        };
        /** SceneCredentialStatusView */
        SceneCredentialStatusView: {
            /** Credential Id */
            credential_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "revoked";
            /** Created At */
            created_at: string;
            /** Last Used At */
            last_used_at: string | null;
            /** Revoked At */
            revoked_at: string | null;
            /** Revoked Reason */
            revoked_reason: string | null;
            /** Token Preview */
            token_preview: string | null;
        };
        /** SceneListResponse */
        SceneListResponse: {
            /** Items */
            items: components["schemas"]["SceneView"][];
        };
        /** SceneStatusResponse */
        SceneStatusResponse: {
            scene: components["schemas"]["SceneView"];
            credential: components["schemas"]["SceneCredentialStatusView"] | null;
        };
        /**
         * SceneUpdateRequest
         * @description Full desired metadata state; the same validation rules as creation.
         *
         *     The web client always submits both fields together, so ``description=null``
         *     unambiguously clears the description.
         */
        SceneUpdateRequest: {
            /** Name */
            name: string;
            /** Description */
            description?: string | null;
        };
        /** SceneView */
        SceneView: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Description */
            description: string | null;
            /** Created At */
            created_at: string;
            /** Question Count */
            question_count: number;
            /** Active Credential Count */
            active_credential_count: number;
        };
        /** ScoreAnchorIn */
        ScoreAnchorIn: {
            /** Score */
            score: number;
            /** Description */
            description: string;
        };
        /** ScoreAnchorView */
        ScoreAnchorView: {
            /** Score */
            score: number;
            /** Description */
            description: string;
        };
        /**
         * SourceCitationIn
         * @description Teacher-visible citation into this question's materials.
         */
        SourceCitationIn: {
            /** Locator */
            locator: string;
            /** Quote */
            quote: string;
        };
        /** SourceCitationView */
        SourceCitationView: {
            /** Locator */
            locator: string;
            /** Quote */
            quote: string;
        };
        /** User */
        User: {
            /** Id */
            id: string;
            /** Username */
            username: string;
            /** Email */
            email?: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** UserResponse */
        UserResponse: {
            user: components["schemas"]["User"];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    healthz_healthz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    login_api_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_api_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    me_api_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_scenes_api_scenes_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SceneListResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    create_scene_api_scenes_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SceneCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SceneView"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 同名场景已存在 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_scene_status_api_scenes__scene_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                scene_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SceneStatusResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 场景不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_scene_api_scenes__scene_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                scene_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 场景不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 场景仍有题目 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_scene_api_scenes__scene_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                scene_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SceneUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SceneView"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 场景不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 同名场景已存在 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_or_replace_credential_api_scenes__scene_id__credentials_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                scene_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SceneCredentialIssuedView"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 场景不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reveal_credential_api_scenes__scene_id__credential_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                scene_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SceneCredentialPlaintextView"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 场景不存在或无有效凭证 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 旧版本凭证，明文不可查看 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_credential_api_scenes__scene_id__credentials__credential_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                scene_id: string;
                credential_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SceneCredentialStatusView"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 场景凭证不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 凭证已被撤销 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_library_api_questions_get: {
        parameters: {
            query: {
                scene_id: string;
                status?: components["schemas"]["QuestionStatus"] | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionLibraryResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 场景不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_question_api_questions__question_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionDetailResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_question_api_questions__question_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuestionDeleteRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeleteAcceptedResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 状态或版本不允许删除 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 标题确认不匹配 */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    update_title_api_questions__question_id__title_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuestionTitleRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionDetailResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 内容版本陈旧 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_materials_api_questions__question_id__materials_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuestionMaterialsPatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionDetailResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 内容版本陈旧、生成中或已发布 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 材料内容无效 */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    patch_criterion_api_questions__question_id__criteria__criterion_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
                criterion_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CriterionPatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionDetailResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目或评分维度不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 内容版本陈旧、生成中或已发布 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 评分维度无效 */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    regenerate_question_api_questions__question_id__regenerate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuestionCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OperationAcceptedResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 内容版本陈旧或生成中 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    patch_criteria_api_questions__question_id__criteria_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CriteriaPatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionDetailResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 内容版本陈旧或生成中 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 评分维度无效 */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    retry_generation_api_questions__question_id__generation_retry_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuestionCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OperationAcceptedResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 状态或版本不允许重试 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    publish_api_questions__question_id__publication_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuestionCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionDetailResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 状态不允许发布 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    review_reopen_api_questions__question_id__review_reopen_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                question_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QuestionCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionDetailResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 状态或版本不允许重新打开 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_run_events_api_questions__question_id__runs__operation_id__events_get: {
        parameters: {
            query?: {
                after_sequence?: number;
            };
            header?: never;
            path: {
                question_id: string;
                operation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunEventsResponse"];
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 运行已被取代或删除冻结 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    stream_run_events_api_questions__question_id__runs__operation_id__events_stream_get: {
        parameters: {
            query?: {
                after_sequence?: number;
            };
            header?: never;
            path: {
                question_id: string;
                operation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description 未登录 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 题目不存在 */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_connection_status_api_external_connection_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SceneConnectionStatusView"];
                };
            };
            /** @description 凭证缺失或无效 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    upload_question_batch_api_external_question_batches_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BatchUploadRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchUploadResponse"];
                };
            };
            /** @description 凭证缺失或无效 */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 命令冲突或正在处理 */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description 批次内容校验失败 */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
}
