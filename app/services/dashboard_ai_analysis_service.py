from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ProjectPermission
from app.db.session import SessionLocal
from app.models.dashboard import DashboardAIAnalysisJob
from app.models.project import ProjectEnvironment
from app.models.user import User
from app.schemas.ai import AIChatRequest
from app.schemas.dashboard import (
    CreateDashboardAIJobRequest,
    DashboardAction,
    DashboardAIJobAccepted,
    DashboardAIJobResult,
    DashboardEvidence,
    DashboardRecommendation,
)
from app.services.ai_service import AIService
from app.services.dashboard_service import DashboardService
from app.services.permission_service import PermissionService


class DashboardAIAnalysisService:
    RECOMMENDATION_TYPES = {
        "failure_analysis",
        "assertion_optimization",
        "environment_fix",
        "regression",
        "defect_creation",
        "coverage_improvement",
    }
    PRIORITIES = {"P0", "P1", "P2", "P3"}
    RISK_LEVELS = {"critical", "high", "medium", "low"}

    def __init__(self, db: Session, ai_service: AIService | None = None):
        self.db = db
        self.ai_service = ai_service or AIService()
        self.permission_service = PermissionService(db)

    def create_job(
        self,
        *,
        payload: CreateDashboardAIJobRequest,
        current_user: User,
    ) -> DashboardAIJobAccepted:
        self.permission_service.require_project_permission(
            current_user,
            payload.project_id,
            ProjectPermission.ANALYZE_AI.value,
        )
        self._validate_environment(payload.project_id, payload.environment_id)
        now = datetime.now()
        job = DashboardAIAnalysisJob(
            id=f"dashboard-ai-{uuid.uuid4().hex}",
            project_id=payload.project_id,
            environment_id=payload.environment_id,
            created_by_id=current_user.id,
            range_value=payload.range,
            analysis_type=payload.analysis_type,
            focus=payload.focus.model_dump(mode="json") if payload.focus else {},
            user_prompt=payload.user_prompt,
            status="queued",
            progress=0,
            recommendations=[],
            evidence=[],
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return DashboardAIJobAccepted(
            job_id=job.id,
            status="queued",
            analysis_type=job.analysis_type,
            created_at=job.created_at,
            poll_after_ms=1000,
        )

    def get_job(self, *, job_id: str, current_user: User) -> DashboardAIJobResult:
        job = self._job_or_404(job_id)
        self.permission_service.require_project_access(current_user, job.project_id)
        return self._to_result(job)

    @classmethod
    def execute_queued_job(cls, job_id: str) -> None:
        with SessionLocal() as db:
            cls(db)._execute(job_id)

    def _execute(self, job_id: str) -> None:
        job = self._job_or_404(job_id)
        if job.status != "queued":
            return
        try:
            job.status = "running"
            job.progress = 10
            self.db.commit()
            self.db.refresh(job)
            evidence = self._collect_evidence(job)
            job.evidence = [item.model_dump(mode="json") for item in evidence]
            job.progress = 45
            self.db.commit()

            if job.analysis_type == "defect_prediction":
                job.summary = "当前系统尚未部署经过历史数据校准和效果验证的缺陷预测模型。"
                job.recommendations = []
                job.status = "completed"
                job.progress = 100
                job.generated_at = datetime.now()
                self.db.commit()
                return

            if not evidence:
                job.summary = "当前筛选范围内没有可用于分析的执行或缺陷证据。"
                job.recommendations = []
                job.status = "completed"
                job.progress = 100
                job.generated_at = datetime.now()
                self.db.commit()
                return

            response = self.ai_service.chat(
                AIChatRequest(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是自动化测试平台的质量分析器。只能根据给定证据输出结论，"
                                "不得编造资源、运行、缺陷、概率或指标。输出 JSON，包含 summary 和 recommendations；"
                                "recommendations 每项包含 type、priority、risk_level、confidence_score、title、summary、recommendation。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": self._analysis_prompt(job, evidence),
                        },
                    ],
                    temperature=0.1,
                    max_tokens=1800,
                    response_format="json",
                )
            )
            parsed = self._parse_json(response.content)
            recommendations = self._recommendations_from_model(parsed, evidence)
            job.summary = self._safe_text(parsed.get("summary"), "已根据当前范围内的真实执行与缺陷证据完成分析。", 4000)
            job.recommendations = [item.model_dump(mode="json") for item in recommendations]
            job.status = "completed"
            job.progress = 100
            job.generated_at = datetime.now()
            job.error_code = None
            job.error_message = None
            self.db.commit()
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            failed_job = self.db.get(DashboardAIAnalysisJob, job_id)
            if failed_job is not None:
                failed_job.status = "failed"
                failed_job.progress = 100
                failed_job.error_code = self._error_code(exc)
                failed_job.error_message = self._error_message(exc)
                failed_job.generated_at = datetime.now()
                self.db.commit()

    def _collect_evidence(self, job: DashboardAIAnalysisJob) -> list[DashboardEvidence]:
        user = self.db.get(User, job.created_by_id)
        if user is None:
            raise RuntimeError("分析任务创建用户不存在")
        now = datetime.now()
        started_from = now if job.range_value == "today" else now - timedelta(days=29 if job.range_value == "30d" else 6)
        if job.range_value == "today":
            started_from = datetime.combine(now.date(), datetime.min.time())
        activity = DashboardService(self.db).activity_feed(
            project_id=job.project_id,
            current_user=user,
            environment_id=job.environment_id,
            date_from=started_from,
            date_to=now,
            page=1,
            page_size=100,
        )
        focus = job.focus if isinstance(job.focus, dict) else {}
        focus_type = focus.get("resource_type")
        focus_ids = {str(item) for item in focus.get("resource_ids", [])}
        selected = [
            item for item in activity.items
            if (
                not focus_type
                or item.resource_type == focus_type
                or (focus_type == "execution" and item.run_id is not None)
            )
            and (
                not focus_ids
                or str(item.run_id if focus_type == "execution" else item.resource_id) in focus_ids
            )
        ]
        return [
            DashboardEvidence(
                resource_type=item.resource_type,
                resource_id=item.resource_id,
                resource_name=item.resource_name,
                run_id=item.run_id,
                description=f"{item.title}；{item.detail}",
            )
            for item in selected[:50]
        ]

    def _analysis_prompt(self, job: DashboardAIAnalysisJob, evidence: list[DashboardEvidence]) -> str:
        payload = {
            "analysis_type": job.analysis_type,
            "range": job.range_value,
            "user_prompt": job.user_prompt,
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
        return json.dumps(payload, ensure_ascii=False)

    def _recommendations_from_model(
        self,
        parsed: dict,
        evidence: list[DashboardEvidence],
    ) -> list[DashboardRecommendation]:
        raw_items = parsed.get("recommendations")
        if not isinstance(raw_items, list):
            return []
        result: list[DashboardRecommendation] = []
        for index, raw in enumerate(raw_items[:10], start=1):
            if not isinstance(raw, dict):
                continue
            recommendation_type = str(raw.get("type") or "failure_analysis").strip()
            if recommendation_type not in self.RECOMMENDATION_TYPES:
                recommendation_type = "failure_analysis"
            priority = str(raw.get("priority") or "P2").upper()
            if priority not in self.PRIORITIES:
                priority = "P2"
            risk_level = str(raw.get("risk_level") or "medium").lower()
            if risk_level not in self.RISK_LEVELS:
                risk_level = "medium"
            try:
                confidence = max(0.0, min(100.0, float(raw.get("confidence_score", 50))))
            except (TypeError, ValueError):
                confidence = 50.0
            supporting_evidence = evidence[:3]
            result.append(
                DashboardRecommendation(
                    id=f"recommendation-{index}",
                    type=recommendation_type,
                    priority=priority,
                    risk_level=risk_level,
                    confidence_score=confidence,
                    title=self._safe_text(raw.get("title"), "质量改进建议", 200),
                    summary=self._safe_text(raw.get("summary"), "基于当前证据生成。", 1000),
                    recommendation=self._safe_text(raw.get("recommendation"), "请核对关联证据后处理。", 2000),
                    evidence=supporting_evidence,
                    action=self._action_for(recommendation_type, supporting_evidence),
                )
            )
        return result

    @staticmethod
    def _action_for(
        recommendation_type: str,
        evidence: list[DashboardEvidence],
    ) -> DashboardAction | None:
        if not evidence:
            return None
        first = evidence[0]
        if recommendation_type == "regression":
            return DashboardAction(
                code="rerun",
                label="发起回归",
                resource_type=first.resource_type,
                resource_id=first.resource_id,
            )
        if recommendation_type == "assertion_optimization":
            code = "optimize_assertions"
            label = "优化断言"
        elif recommendation_type == "defect_creation":
            code = "generate_defect"
            label = "生成缺陷"
        else:
            code = "view_failure_analysis" if first.run_id is not None else "view_test_case"
            label = "查看失败分析" if first.run_id is not None else "查看资源"
        return DashboardAction(
            code=code,
            label=label,
            resource_type="execution" if first.run_id is not None else first.resource_type,
            resource_id=first.run_id if first.run_id is not None else first.resource_id,
        )

    def _validate_environment(self, project_id: int, environment_id: int | None) -> None:
        if environment_id is None:
            return
        environment = self.db.scalar(
            select(ProjectEnvironment.id).where(
                ProjectEnvironment.id == environment_id,
                ProjectEnvironment.project_id == project_id,
                ProjectEnvironment.is_deleted.is_(False),
            )
        )
        if environment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目环境不存在")

    def _job_or_404(self, job_id: str) -> DashboardAIAnalysisJob:
        job = self.db.get(DashboardAIAnalysisJob, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 分析任务不存在")
        return job

    @staticmethod
    def _to_result(job: DashboardAIAnalysisJob) -> DashboardAIJobResult:
        return DashboardAIJobResult(
            job_id=job.id,
            status=job.status,
            progress=job.progress,
            analysis_type=job.analysis_type,
            summary=job.summary,
            recommendations=job.recommendations or [],
            evidence=job.evidence or [],
            generated_at=job.generated_at,
            error_code=job.error_code,
            error_message=job.error_message,
        )

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = (content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("AI 分析结果不是 JSON 对象")
        return parsed

    @staticmethod
    def _safe_text(value, fallback: str, limit: int) -> str:
        text = str(value or "").strip()
        return (text or fallback)[:limit]

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, HTTPException):
            if exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
                return "ai_provider_not_configured"
            if exc.status_code in {status.HTTP_502_BAD_GATEWAY, status.HTTP_503_SERVICE_UNAVAILABLE}:
                return "ai_provider_unavailable"
        if isinstance(exc, (json.JSONDecodeError, ValueError)):
            return "invalid_ai_response"
        return "analysis_failed"

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, HTTPException):
            return str(exc.detail)[:1000]
        return str(exc)[:1000] or "AI 分析失败"
