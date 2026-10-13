from pydantic import BaseModel, Field
from typing import List, Optional

class PredictiveFeatures(BaseModel):
    """
    Schema for the 21 predictive features required by the dropout model.
    """
    highest_education: str = Field(..., description="Highest education level on entry")
    num_of_prev_attempts: int = Field(..., ge=0, description="Number of previous attempts")
    studied_credits: int = Field(..., ge=0, description="Total number of credits studied")
    registration_day: int = Field(..., description="Registration date relative to module presentation start")
    code_module: str = Field(..., description="Module code (e.g., AAA, BBB)")
    code_presentation: str = Field(..., description="Presentation code (e.g., 2013J, 2014B)")
    module_presentation_length: int = Field(..., gt=0, description="Length of the module presentation in days")
    
    asm_submission_count: float = Field(..., ge=0, description="Number of assessments submitted by day 28")
    asm_mean_score: Optional[float] = Field(..., description="Mean score on assessments submitted by day 28 (null if no scored submissions)")
    asm_score_std: Optional[float] = Field(..., description="Standard deviation of assessment scores (null if fewer than two scored submissions)")
    asm_failed_count: float = Field(..., ge=0, description="Number of failed assessments by day 28")
    asm_average_delay: Optional[float] = Field(..., description="Average delay in days for assessment submission (null if no submissions)")
    
    vle_total_clicks: float = Field(..., ge=0, description="Total VLE clicks by day 28")
    vle_active_days: float = Field(..., ge=0, description="Number of days active on the VLE by day 28")
    vle_days_since_last_activity: Optional[float] = Field(..., ge=0, description="Days since last VLE activity before day 28 (null if no VLE activity)")
    vle_clicks_last_7_days: float = Field(..., ge=0, description="VLE clicks between day 21 and 28")
    vle_clicks_last_14_days: float = Field(..., ge=0, description="VLE clicks between day 14 and 28")
    vle_forum_clicks: float = Field(..., ge=0, description="VLE clicks on forum resources")
    vle_resource_clicks: float = Field(..., ge=0, description="VLE clicks on standard resources")
    vle_quiz_clicks: float = Field(..., ge=0, description="VLE clicks on quizzes/assessments")
    vle_activity_type_diversity: float = Field(..., ge=0, description="Number of distinct VLE activity types accessed")
    gender: Optional[str] = Field(None, description="Optional sensitive attribute for fairness-adjusted decision. Not used for probability prediction.")

class SHAPExplanation(BaseModel):
    """
    Schema for local SHAP explanation features.
    """
    feature: str = Field(..., description="Name of the feature")
    contribution: float = Field(..., description="SHAP value for the feature")
    direction: str = Field(..., description="Positive (increases risk) or Negative (decreases risk)")


class PredictionResponse(BaseModel):
    """
    Schema for the overall API response.
    """
    risk_probability: float = Field(..., ge=0.0, le=1.0, description="Predicted probability of dropping out (withdrawing)")
    risk_tier: str = Field(..., description="Categorical risk tier (LOW, MODERATE, HIGH, CRITICAL)")
    priority_score: float = Field(..., description="Score used for prioritization, currently equals risk_probability")
    human_review_required: bool = Field(..., description="Whether human review is required")
    intervention_level: str = Field(..., description="Level of intervention recommended")
    recommended_actions: List[str] = Field(..., description="Recommended actions for the advisor")
    
    fairness_adjusted_decision: Optional[int] = Field(None, description="Binary decision (1=Withdrawn) from ThresholdOptimizer")
    fairness_status: str = Field(..., description="Status of the fairness decision (e.g., Applied, Unavailable: gender missing)")
    
    top_positive_contributors: Optional[List[SHAPExplanation]] = Field(None, description="Features pushing risk higher")
    top_negative_contributors: Optional[List[SHAPExplanation]] = Field(None, description="Features pushing risk lower")

class HealthResponse(BaseModel):
    status: str
    model_loaded: bool


# ---------------------------------------------------------------------------
# v1 API schemas (web UI + batch scoring). The legacy models above are unchanged.
# ---------------------------------------------------------------------------

class FeatureContribution(BaseModel):
    """SHAP contribution of one raw input feature (one-hot columns summed)."""
    feature: str = Field(..., description="Raw input feature name")
    label: str = Field(..., description="Human-readable feature label")
    value: Optional[float | str] = Field(None, description="Input value supplied for this feature")
    contribution: float = Field(..., description="Summed SHAP value in log-odds space")


class ExplanationDetail(BaseModel):
    backend: str = Field(..., description="Engine that produced the SHAP values")
    base_value: float = Field(..., description="Expected model output (log-odds) before any feature contributes")
    contributions: List[FeatureContribution] = Field(..., description="All 21 features, sorted by |contribution|")


class PredictionResponseV1(PredictionResponse):
    """Legacy response plus traceability fields used by the web UI."""
    prediction_id: str = Field(..., description="Opaque id of this prediction (no student identifiers)")
    model_version: str = Field(..., description="Short SHA-256 of the served model artifact")
    latency_ms: float = Field(..., description="Server-side inference time in milliseconds")
    missing_features: List[str] = Field(default_factory=list, description="Features supplied as null")
    explanation: Optional[ExplanationDetail] = None


class BatchStudent(PredictiveFeatures):
    record_id: Optional[str] = Field(None, max_length=128, description="Caller-side row reference echoed back in results")


class BatchPredictionRequest(BaseModel):
    students: List[BatchStudent] = Field(..., min_length=1, description="Students to score")
    include_explanation: bool = Field(False, description="Attach the top risk drivers to every row")


class BatchRowResult(BaseModel):
    index: int
    record_id: Optional[str] = None
    risk_probability: float
    risk_tier: str
    intervention_level: str
    human_review_required: bool
    fairness_adjusted_decision: Optional[int] = None
    fairness_status: str
    missing_features: List[str] = Field(default_factory=list)
    top_drivers: Optional[List[FeatureContribution]] = None


class BatchSummary(BaseModel):
    count: int
    mean_risk_probability: float
    median_risk_probability: float
    max_risk_probability: float
    human_review_count: int
    human_review_rate: float
    tier_counts: dict


class BatchPredictionResponse(BaseModel):
    model_version: str
    latency_ms: float
    summary: BatchSummary
    results: List[BatchRowResult]
