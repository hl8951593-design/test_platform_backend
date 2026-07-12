import base64
from typing import Any

from app.core.sensitive_data import mask_sensitive
from app.schemas.execution_diagnostic import (
    CanonicalExecutionDiagnostic,
    CanonicalStepDiagnostic,
    DiagnosticOmission,
    DiagnosticPage,
    ExecutionDiagnosticEnvelope,
    ExecutionDiagnosticQuery,
)
from app.schemas.execution_record import ExecutionType
from app.services.execution_failure_signature import (
    assertion_summaries,
    classify_failure,
    is_failure,
    response_summary,
)


_FAILURE_STATUSES = {"failed", "timeout", "error"}


class ExecutionDiagnosticProjectionService:
    def canonicalize(
        self, *, execution_type: ExecutionType, execution: dict[str, Any]
    ) -> CanonicalExecutionDiagnostic:
        summary = execution.get("summary") if isinstance(execution, dict) else {}
        detail = execution.get("detail") if isinstance(execution, dict) else {}
        summary = summary if isinstance(summary, dict) else {}
        detail = detail if isinstance(detail, dict) else {}
        raw_steps = self._protocol_steps(execution_type=execution_type, detail=detail)
        steps = [
            self.canonicalize_step(
                execution_type=execution_type, step=step, fallback_index=index
            )
            for index, step in enumerate(raw_steps)
        ]
        first_failure = next((step for step in steps if self._failed(step.status)), None)
        failure_identity = None
        if first_failure is not None:
            failure_identity = classify_failure(
                execution_type=execution_type,
                step=first_failure.normalized_detail,
            )
        execution_id = self._execution_id(summary)
        resource_ref = str(summary.get("id") or f"{execution_type}:{execution_id}")
        return CanonicalExecutionDiagnostic(
            resource_ref=resource_ref,
            execution_type=execution_type,
            execution_id=execution_id,
            summary=self._summary(summary),
            counts=self._counts(steps),
            steps=steps,
            first_failure_step_id=first_failure.step_id if first_failure else None,
            failure_category=failure_identity.category if failure_identity else None,
            failure_signature=failure_identity.signature if failure_identity else None,
        )

    def canonicalize_step(
        self,
        *,
        execution_type: ExecutionType,
        step: dict[str, Any],
        fallback_index: int,
    ) -> CanonicalStepDiagnostic:
        source = step if isinstance(step, dict) else {}
        step_id = str(
            source.get("step_id")
            or source.get("node_id")
            or source.get("id")
            or f"{execution_type.upper()}-{fallback_index + 1}"
        )
        return CanonicalStepDiagnostic(
            step_id=step_id,
            step_index=self._safe_int(source.get("step_index"), fallback_index),
            node_id=self._bounded(source.get("node_id"), 128),
            node_phase=self._bounded(
                source.get("node_phase") or source.get("phase"), 64
            ),
            name=self._bounded(
                source.get("name")
                or source.get("step_name")
                or source.get("node_name")
                or step_id,
                256,
            )
            or step_id,
            kind=self._bounded(
                source.get("kind")
                or source.get("type")
                or source.get("node_type")
                or execution_type,
                64,
            )
            or execution_type,
            status=str(source.get("status") or "unknown").lower(),
            duration_ms=self._optional_int(
                source.get("duration_ms") or source.get("elapsed_ms")
            ),
            error_code=self._bounded(source.get("error_code"), 128),
            error_message=self._bounded(
                source.get("error_message") or source.get("error"), 512
            ),
            assertions=assertion_summaries(source),
            response=response_summary(source),
            bindings=self._named_items(
                source.get("resolved_bindings") or source.get("bindings"),
                source_keys=("source", "from", "path"),
            ),
            extractors=self._named_items(
                source.get("extracted_variables") or source.get("extractors"),
                source_keys=("source", "path", "type"),
            ),
            retries=self._retry_summary(source),
            normalized_detail=mask_sensitive(source),
        )

    def project(
        self,
        *,
        execution_type: ExecutionType,
        execution: dict[str, Any],
        query: ExecutionDiagnosticQuery,
    ) -> ExecutionDiagnosticEnvelope:
        canonical = self.canonicalize(
            execution_type=execution_type, execution=execution
        )
        if query.view == "summary":
            return self._envelope(
                canonical,
                query,
                data=self._summary_data(canonical),
                recommended=["failures"] if canonical.first_failure_step_id else [],
            )
        if query.view == "artifact":
            return self._envelope(
                canonical,
                query,
                data={"artifact_ref": query.selector.artifact_ref},
                omissions=[
                    DiagnosticOmission(
                        section="artifact.content",
                        reason="artifact_externalized",
                        reference=query.selector.artifact_ref,
                    )
                ],
                complete=False,
            )

        selected = self._select_steps(canonical=canonical, query=query)
        if query.view == "failures":
            step_views = [self._step_view(step) for step in selected]
            first = next(
                (
                    item
                    for item in step_views
                    if item["step_id"] == canonical.first_failure_step_id
                ),
                step_views[0] if step_views else None,
            )
            data = {
                **self._summary_data(canonical),
                "first_failure": first,
                "failures": step_views,
            }
        elif query.view == "step":
            data = {
                **self._summary_data(canonical),
                "step": self._step_view(selected[0]) if selected else None,
            }
        else:
            data = {
                **self._summary_data(canonical),
                "steps": [self._step_view(step) for step in selected],
            }
        return self._budgeted_envelope(
            canonical=canonical,
            query=query,
            data=data,
            selected=selected,
        )

    @staticmethod
    def _protocol_steps(
        *, execution_type: ExecutionType, detail: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if execution_type == "scenario":
            raw = detail.get("step_results") or []
        elif execution_type == "flow":
            raw = detail.get("node_executions") or []
        else:
            raw = [detail]
        return [item for item in raw if isinstance(item, dict)]

    def _select_steps(
        self,
        *,
        canonical: CanonicalExecutionDiagnostic,
        query: ExecutionDiagnosticQuery,
    ) -> list[CanonicalStepDiagnostic]:
        steps = canonical.steps
        if query.view == "failures":
            statuses = {item.lower() for item in query.selector.statuses}
            steps = [step for step in steps if step.status in statuses]
        elif query.view == "step":
            target = query.selector.step_ids[0]
            steps = [step for step in steps if step.step_id == target]
        elif query.selector.step_ids:
            targets = set(query.selector.step_ids)
            steps = [step for step in steps if step.step_id in targets]
        elif query.selector.statuses:
            statuses = {item.lower() for item in query.selector.statuses}
            steps = [step for step in steps if step.status in statuses]
        if query.view in {"steps", "full"} and not query.selector.step_ids:
            steps = sorted(
                steps,
                key=lambda step: (
                    0 if self._failed(step.status) else 1,
                    step.step_index,
                ),
            )
        offset = self._decode_cursor(query.cursor, query.selector.offset)
        return steps[offset : offset + query.limit]

    def _budgeted_envelope(
        self,
        *,
        canonical: CanonicalExecutionDiagnostic,
        query: ExecutionDiagnosticQuery,
        data: dict[str, Any],
        selected: list[CanonicalStepDiagnostic],
    ) -> ExecutionDiagnosticEnvelope:
        collection_key = "failures" if query.view == "failures" else "steps"
        if query.view == "step":
            return self._fit_single_view(canonical, query, data)
        original_items = list(data.get(collection_key) or [])
        data[collection_key] = []
        omissions: list[DiagnosticOmission] = []
        envelope = self._envelope(canonical, query, data=data)
        for item in self._failure_first(original_items):
            data[collection_key].append(item)
            candidate = self._envelope(canonical, query, data=data)
            if len(candidate.model_dump_json()) > query.max_chars:
                data[collection_key].pop()
                if not omissions:
                    omissions.append(
                        DiagnosticOmission(
                            section=f"{collection_key}.remaining",
                            reason="budget_exceeded",
                            reference=f"{canonical.resource_ref}/steps",
                        )
                    )
            else:
                envelope = candidate
        included_ids = {item.get("step_id") for item in data[collection_key]}
        if query.view == "failures":
            first = data.get("first_failure")
            if first and first.get("step_id") not in included_ids:
                compact_first = self._compact_step(first)
                data["first_failure"] = compact_first
        has_more = len(data[collection_key]) < len(original_items)
        next_cursor = None
        if has_more:
            next_cursor = self._encode_cursor(
                self._decode_cursor(query.cursor, query.selector.offset)
                + len(data[collection_key])
            )
        envelope = self._envelope(
            canonical,
            query,
            data=data,
            omissions=omissions,
            page=DiagnosticPage(next_cursor=next_cursor, has_more=has_more),
            complete=not has_more,
            recommended=["step"] if has_more else [],
        )
        return self._hard_fit(envelope, query.max_chars)

    def _fit_single_view(
        self,
        canonical: CanonicalExecutionDiagnostic,
        query: ExecutionDiagnosticQuery,
        data: dict[str, Any],
    ) -> ExecutionDiagnosticEnvelope:
        envelope = self._envelope(canonical, query, data=data)
        if len(envelope.model_dump_json()) <= query.max_chars:
            return envelope
        if isinstance(data.get("step"), dict):
            data["step"] = self._compact_step(data["step"])
        envelope = self._envelope(
            canonical,
            query,
            data=data,
            omissions=[
                DiagnosticOmission(
                    section="step.detail",
                    reason="budget_exceeded",
                    reference=f"{canonical.resource_ref}/steps/{query.selector.step_ids[0]}",
                )
            ],
            complete=False,
        )
        return self._hard_fit(envelope, query.max_chars)

    @staticmethod
    def _hard_fit(
        envelope: ExecutionDiagnosticEnvelope, max_chars: int
    ) -> ExecutionDiagnosticEnvelope:
        if len(envelope.model_dump_json()) <= max_chars:
            return envelope
        data = dict(envelope.data)
        for key in ("steps", "failures"):
            if key in data:
                data[key] = []
        if "first_failure" in data and isinstance(data["first_failure"], dict):
            data["first_failure"] = ExecutionDiagnosticProjectionService._compact_step(
                data["first_failure"]
            )
        if "step" in data and isinstance(data["step"], dict):
            data["step"] = ExecutionDiagnosticProjectionService._compact_step(data["step"])
        envelope.data = data
        envelope.diagnostic_complete = False
        envelope.page.has_more = True
        if len(envelope.model_dump_json()) <= max_chars:
            return envelope
        envelope.data = {
            "counts": data.get("counts", {}),
            "failure_category": data.get("failure_category"),
            "failure_signature": data.get("failure_signature"),
        }
        return envelope

    @staticmethod
    def _envelope(
        canonical: CanonicalExecutionDiagnostic,
        query: ExecutionDiagnosticQuery,
        *,
        data: dict[str, Any],
        omissions: list[DiagnosticOmission] | None = None,
        page: DiagnosticPage | None = None,
        complete: bool = True,
        recommended: list[Any] | None = None,
    ) -> ExecutionDiagnosticEnvelope:
        return ExecutionDiagnosticEnvelope(
            resource_ref=canonical.resource_ref,
            view=query.view,
            data=data,
            omissions=omissions or [],
            page=page or DiagnosticPage(),
            diagnostic_complete=complete,
            recommended_next_views=recommended or [],
        )

    @staticmethod
    def _summary_data(canonical: CanonicalExecutionDiagnostic) -> dict[str, Any]:
        return {
            "summary": canonical.summary,
            "counts": canonical.counts,
            "first_failure_step_id": canonical.first_failure_step_id,
            "failure_category": canonical.failure_category,
            "failure_signature": canonical.failure_signature,
        }

    @staticmethod
    def _step_view(step: CanonicalStepDiagnostic) -> dict[str, Any]:
        return step.model_dump(exclude={"normalized_detail"}, exclude_none=True)

    @staticmethod
    def _compact_step(step: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "step_id",
            "step_index",
            "node_id",
            "name",
            "kind",
            "status",
            "duration_ms",
            "error_code",
            "error_message",
            "response",
        )
        return {key: step[key] for key in keys if key in step}

    @staticmethod
    def _failure_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: (
                0 if str(item.get("status") or "").lower() in _FAILURE_STATUSES else 1,
                int(item.get("step_index") or 0),
            ),
        )

    @staticmethod
    def _counts(steps: list[CanonicalStepDiagnostic]) -> dict[str, int]:
        counts = {
            "total": len(steps),
            "passed": 0,
            "failed": 0,
            "timeout": 0,
            "skipped": 0,
        }
        for step in steps:
            status = step.status
            if status == "error":
                status = "failed"
            if status in counts:
                counts[status] += 1
        return counts

    def _summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        allowed = (
            "id",
            "execution_type",
            "execution_id",
            "project_id",
            "resource_id",
            "resource_name",
            "environment_id",
            "status",
            "trigger_type",
            "duration_ms",
            "error_message",
            "started_at",
            "finished_at",
            "created_at",
        )
        result: dict[str, Any] = {}
        for key in allowed:
            value = summary.get(key)
            if value is None:
                continue
            if key in {"resource_name", "error_message"}:
                value = self._bounded(value, 512)
            elif not isinstance(value, (str, int, float, bool)):
                value = str(value)
            result[key] = value
        return result

    @staticmethod
    def _named_items(
        value: Any, *, source_keys: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            items = [
                {"name": key, "value": item}
                for key, item in value.items()
            ]
        elif isinstance(value, list):
            items = value
        else:
            return []
        result: list[dict[str, Any]] = []
        for item in items[:100]:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("key") or item.get("variable")
            source = next(
                (item.get(key) for key in source_keys if item.get(key) is not None), None
            )
            result.append(
                {
                    key: bounded
                    for key, bounded in {
                        "name": ExecutionDiagnosticProjectionService._bounded(name, 128),
                        "source": ExecutionDiagnosticProjectionService._bounded(source, 256),
                    }.items()
                    if bounded is not None
                }
            )
        return result

    @staticmethod
    def _retry_summary(step: dict[str, Any]) -> dict[str, Any]:
        history = step.get("attempt_history") or step.get("retries")
        if isinstance(history, list):
            return {"attempt_count": len(history)}
        if isinstance(history, dict):
            allowed = ("attempt_count", "max_attempts", "retried", "reason")
            return {
                key: value
                for key in allowed
                if (value := history.get(key)) is not None
            }
        retry_count = step.get("retry_count")
        return {"attempt_count": retry_count} if isinstance(retry_count, int) else {}

    @staticmethod
    def _execution_id(summary: dict[str, Any]) -> int:
        value = summary.get("execution_id")
        if isinstance(value, int):
            return value
        resource_ref = str(summary.get("id") or "0")
        try:
            return int(resource_ref.rsplit(":", 1)[-1])
        except ValueError:
            return 0

    @staticmethod
    def _failed(status: str) -> bool:
        return status.lower() in _FAILURE_STATUSES

    @staticmethod
    def _safe_int(value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bounded(value: Any, max_chars: int) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if len(text) <= max_chars else text[:max_chars]

    @staticmethod
    def _encode_cursor(offset: int) -> str:
        return base64.urlsafe_b64encode(str(offset).encode()).decode()

    @staticmethod
    def _decode_cursor(cursor: str | None, fallback: int) -> int:
        if not cursor:
            return fallback
        try:
            return int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except (ValueError, UnicodeDecodeError):
            return fallback
