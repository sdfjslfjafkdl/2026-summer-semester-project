"""투자계획서 작성 지원 응답 스키마.

기존 봉투 규약(app/schemas/envelope.py)을 그대로 따른다. data 에 값, meta 에 출처.
계획서에 들어간 모든 수치는 어느 Layer 1 엔드포인트에서 왔는지 data_points 로 추적한다.
사람이 직접 넣은 값은 source="human_input" 으로 구분해 표시한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FillMode = Literal["auto", "assisted", "manual"]
SectionStatus = Literal["filled", "awaiting_human", "placeholder"]
ContentSource = Literal["layer1", "human_input", "template", "llm", "none"]


class SectionGuidance(BaseModel):
    writing_guide: str = Field(description="안내서의 【작성내용】")
    evaluation_focus: str = Field(description="안내서의 【기술 방향과 평가의 주안점】")
    reference_note: str = Field(description="안내서의 【참고사항】")
    source_page: int = Field(description="안내서 쪽 번호", examples=[35])


class DataPoint(BaseModel):
    label: str = Field(description="수치의 이름", examples=["2024년 집행률"])
    value: float | None = Field(description="값", examples=[63.95])
    unit: str = Field(description="단위", examples=["%"])
    source_endpoint: str = Field(
        description="이 수치가 나온 곳. human_input 이면 사람이 직접 넣은 값.",
        examples=["/api/funds/local-extinction/regions"],
    )


class SectionState(BaseModel):
    section_id: str = Field(examples=["6-2-1"])
    number: str = Field(description="서식의 항목 번호", examples=["Ⅵ-2-①"])
    chapter: str = Field(examples=["Ⅵ"])
    title: str = Field(examples=["연도별 기금사업 추진 성과표"])
    fill_mode: FillMode
    status: SectionStatus = Field(
        description="filled: 채워짐 / awaiting_human: 사람 입력 대기 / placeholder: 빈 구획"
    )
    content: str | None = Field(default=None, description="본문. 비어 있으면 null")
    source: ContentSource = Field(default="none", description="내용의 출처")
    data_points: list[DataPoint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    guidance: SectionGuidance
    manual_remainder: str | None = Field(
        default=None, description="자동으로 채우지 못해 사람이 이어서 써야 하는 부분"
    )
    version: int = Field(default=1)
    updated_at: str


class PlanProgress(BaseModel):
    total_sections: int = Field(examples=[27])
    auto_filled: int = Field(description="데이터로 자동 채운 섹션 수", examples=[2])
    assisted_pending: int = Field(description="사람이 값을 주면 문장이 되는 섹션 수", examples=[5])
    manual_pending: int = Field(description="사람이 직접 써야 하는 섹션 수", examples=[20])
    awaiting_human: int = Field(description="사람 입력 대기 총합", examples=[25])
    filled: int = Field(description="내용이 채워진 섹션 수", examples=[2])
    completion_pct: float = Field(description="채워진 섹션 비율(%)", examples=[7.41])


class PlanVersionEntry(BaseModel):
    version: int
    created_at: str
    action: str = Field(description="draft | section_update | revise", examples=["draft"])
    changed_sections: list[str] = Field(default_factory=list)
    note: str | None = None


class PlanDraftData(BaseModel):
    plan_id: str = Field(examples=["plan_제천시_2026_01"])
    region: str = Field(examples=["제천시"])
    year: int = Field(examples=[2026])
    version: int = Field(examples=[1])
    created_at: str
    template_source: str
    sections: list[SectionState]
    progress: PlanProgress
    called_endpoints: list[str] = Field(description="초안을 만들 때 호출한 Layer 1 엔드포인트")


class PlanDetailData(PlanDraftData):
    history: list[PlanVersionEntry] = Field(default_factory=list)


class SectionUpdateRequest(BaseModel):
    content: str = Field(
        description=(
            "manual 섹션은 이 값을 그대로 저장한다. "
            "assisted 섹션은 이 값을 재료로 서식 톤의 문장을 만든다."
        ),
        examples=["부지는 제천시 신월동 934-2번지 시유지이며 2025년 12월 확보 완료"],
        min_length=1,
    )
    values: dict[str, str | float] | None = Field(
        default=None,
        description="assisted 섹션에서 문장 생성에 쓸 항목별 값. 여기 넣은 수치는 사람 입력으로 표시된다.",
        examples=[{"사업명": "청년 정착 지원사업", "총사업비": 20000}],
    )


class SectionUpdateData(BaseModel):
    plan_id: str
    version: int
    section: SectionState
    progress: PlanProgress
    rejected_numbers: list[str] = Field(
        default_factory=list,
        description="도구 결과에도 사람 입력에도 없어 문장에서 제거된 숫자",
    )


class ReviseRequest(BaseModel):
    instruction: str = Field(
        description="자연어 수정 지시문",
        examples=["Ⅲ-3 사업목표의 연차별 목표값을 더 보수적으로 잡아줘"],
        min_length=1,
    )


class SectionChange(BaseModel):
    section_id: str
    number: str
    title: str
    summary: str = Field(description="무엇을 왜 바꿨는지 한 문장", examples=["연차별 목표값을 최근 3년 평균 개선폭의 절반으로 낮췄습니다."])
    before: str | None
    after: str | None
    diff: list[str] = Field(description="unified diff 줄 목록")


class ReviseData(BaseModel):
    plan_id: str
    version: int
    instruction: str
    resolved: bool = Field(
        description="수정 대상 섹션을 판별했는지. false 면 되묻는 응답이다.", examples=[True]
    )
    clarification_question: str | None = Field(
        default=None, description="대상을 못 정했을 때 사용자에게 되묻는 문장"
    )
    candidate_sections: list[str] = Field(
        default_factory=list, description="되물을 때 제시하는 후보 섹션"
    )
    changed_sections: list[str] = Field(default_factory=list)
    changes: list[SectionChange] = Field(default_factory=list)
    progress: PlanProgress | None = None


class PlanSummaryData(BaseModel):
    plan_id: str
    region: str
    year: int
    summary_sentences: list[str] = Field(
        description="비전문가용 요약. 다섯 문장 이내.", max_length=5
    )
    evidence: list[DataPoint] = Field(default_factory=list, description="요약이 인용한 수치와 출처")
    missing_required_sections: list[str] = Field(
        default_factory=list, description="아직 비어 있는 필수 섹션 번호"
    )
    is_submittable: bool = Field(description="필수 섹션이 모두 찼는지", examples=[False])


class ExportRequest(BaseModel):
    format: Literal["docx", "pdf"] = Field(default="docx", examples=["docx"])
