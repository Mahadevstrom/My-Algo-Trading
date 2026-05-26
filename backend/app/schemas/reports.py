from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class ReportIssue(BaseModel):
    severity: str
    code: str
    message: str


class ReportRecommendation(BaseModel):
    code: str
    message: str | None = None


class ReportSnapshotResponse(BaseModel):
    report_type: str
    generated_at: datetime
    trading_mode: str
    live_order_status: str
    report_status: str
    warnings: list[str]
    errors: list[str]
    recommendations: list[str]
    paper_only_safety_confirmed: bool
    sections: dict[str, Any]


class ReportingStatusResponse(BaseModel):
    enabled: bool
    supported_formats: list[str]
    default_lookback_days: int
    live_order_status: str


class SystemHealthReport(ReportSnapshotResponse):
    pass


class DailyReviewReport(ReportSnapshotResponse):
    report_date: date | None = None


class StrategyEvaluationReport(ReportSnapshotResponse):
    pass


class LivePaperReport(ReportSnapshotResponse):
    pass


class MarketFlowReport(ReportSnapshotResponse):
    pass


class SectorBreadthReport(ReportSnapshotResponse):
    pass


class ParticipantFlowReport(ReportSnapshotResponse):
    pass


class DataQualityReport(ReportSnapshotResponse):
    pass


class AuditSummaryReport(ReportSnapshotResponse):
    pass


class ExportReportResponse(BaseModel):
    ok: bool
    filename: str
    format: str
    content_type: str
    content: str
    generated_at: datetime
