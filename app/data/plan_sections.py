"""투자계획서 섹션 레지스트리.

출처: 한국지방재정공제회(지역활력지원단), '2026년 지방소멸대응기금 투자계획서 작성 안내서'(2025.1)
      data/raw/plan_template/ 의 PDF 를 그대로 옮겼다.

원칙: 서식에 없는 항목을 만들지 않는다. 목차(Ⅰ~Ⅵ)와 각 항목의 【작성내용】,
【기술 방향과 평가의 주안점】, 【참고사항】은 안내서 문구를 옮긴 것이며,
띄어쓰기만 읽기 좋게 복원했다.

fill_mode 세 가지:
  auto     - 패널·아티팩트 데이터로 서버가 채운다
  assisted - 사람이 값을 주면 서버가 서식 톤의 문장으로 만든다
  manual   - 서버가 채우지 않는다. 빈 구획과 작성 지침만 넣는다

fill_mode 는 "데이터로 채울 수 있는가"로 정한다. 지역 고유의 판단, 조직 구성,
부지·민원, 재원 배분처럼 데이터에 없는 것은 사람 몫으로 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FillMode = Literal["auto", "assisted", "manual"]

TEMPLATE_SOURCE = "2026년 지방소멸대응기금 투자계획서 작성 안내서(한국지방재정공제회, 2025.1)"

# ── 안내서 p.3 '투자계획서 작성 방법' 의 형식 규정 ──────────────────
FORMAT_RULES: dict[str, object] = {
    "body_font": "휴먼명조",
    "body_size_pt": 15,
    "note_font": "중고딕",
    "note_size_pt": 13,
    "margin_top_mm": 15,
    "margin_bottom_mm": 15,
    "margin_left_mm": 20,
    "margin_right_mm": 20,
    "header_mm": 10,
    "footer_mm": 10,
    "page_numbers": True,
    "body_page_limit": 70,
    "body_page_limit_extended": 100,
    "intro_page_limit": 10,  # 서론(Ⅰ, Ⅱ)은 10p 이내
    "summary_page_limit": 10,
    "submission_format": "hwp",
}

CHAPTERS: dict[str, str] = {
    "Ⅰ": "지역 여건분석 및 전망",
    "Ⅱ": "기본방향 및 전략",
    "Ⅲ": "기금사업(내용 및 효과 등)",
    "Ⅳ": "타 재정·정책 연계방안",
    "Ⅴ": "운영 및 관리체계",
    "Ⅵ": "기타",
}


@dataclass(frozen=True)
class PlanSection:
    section_id: str
    number: str
    chapter: str
    title: str
    fill_mode: FillMode
    writing_guide: str  # 【작성내용】
    evaluation_focus: str  # 【기술 방향과 평가의 주안점】
    reference_note: str  # 【참고사항】
    source_page: int  # 안내서 쪽 번호
    required: bool = True
    # auto·assisted 섹션이라도 데이터로 못 채우는 부분이 남으면 여기에 적는다.
    manual_remainder: str | None = None

    @property
    def chapter_title(self) -> str:
        return CHAPTERS[self.chapter]


SECTIONS: tuple[PlanSection, ...] = (
    # ── Ⅰ. 지역 여건분석 및 전망 ────────────────────────────────
    PlanSection(
        section_id="1-1",
        number="Ⅰ-1",
        chapter="Ⅰ",
        title="지역 여건 및 현황분석",
        fill_mode="auto",
        writing_guide=(
            "인구현황, 인구변동 요인 및 전망, 지방소멸 영향요인(입지, 면적, 교통접근성, "
            "주거·산업형태, 자연·지리적 상황 등)에 대하여 지자체가 자체적으로 항목을 선정하여 기술. "
            "지자체의 인구감소 또는 지방소멸 문제와 직접적으로 연관이 있는 요인, "
            "투자계획의 방향·전략·기금사업의 필요성과 직접적으로 연관이 있는 요인을 포함한다."
        ),
        evaluation_focus=(
            "지역 고유의 특성과 지역이 겪고 있는 문제의 원인을 파악할 수 있도록 구체적으로 기술. "
            "사업의 방향 및 전략, 개별 기금사업 도출 등에 필요하다고 판단하는 요인들이 포함되도록 기술."
        ),
        reference_note="그림이나 도표, 위치도, 지형도, 사진 등 활용. 필요한 경우 지역 외 여건(외부요인) 포함.",
        source_page=10,
        manual_remainder=(
            "서버가 채우는 것은 인구현황과 청년 인구이동 추이뿐이다. "
            "입지·면적·교통접근성·주거·산업형태·자연지리 여건은 패널에 없으므로 담당자가 작성한다."
        ),
    ),
    PlanSection(
        section_id="1-2",
        number="Ⅰ-2",
        chapter="Ⅰ",
        title="지역 여건 및 현황분석 시사점",
        fill_mode="assisted",
        writing_guide="지역 여건분석의 시사점과 기금 투자계획의 기본방향 또는 전략방향과의 연관성 기술.",
        evaluation_focus=(
            "여건 및 현황분석의 시사점과 투자계획의 기본방향 또는 전략방향을 "
            "논리적으로 도출하였음을 파악할 수 있도록 기술."
        ),
        reference_note="그림이나 도표 등 활용 가능.",
        source_page=11,
    ),
    # ── Ⅱ. 기본방향 및 전략 (전체 manual) ───────────────────────
    PlanSection(
        section_id="2-1",
        number="Ⅱ-1",
        chapter="Ⅱ",
        title="기본방향 및 전략의 배경과 도출 과정",
        fill_mode="manual",
        writing_guide=(
            "여건분석 결과, 의견수렴의 방법 및 진행경과, 의사결정체계와 과정(주민참여 현황 등), "
            "기존 사업 성과분석 및 환류 개선조치의 체계와 내용, 인구감소지역 대응 기본계획 및 "
            "시행계획과의 연계성 등을 바탕으로 기본방향 및 전략의 배경과 필요성, 도출과정을 기술."
        ),
        evaluation_focus="목표와 추진전략 도출과정의 적절성을 파악할 수 있도록 기술.",
        reference_note=(
            "기술 내용이 많은 항목은 구체적 내용을 증빙으로 대체 가능. "
            "기존 사업 성과분석 및 환류 개선조치는 투자계획과 직접적인 연관이 있는 경우에 한함."
        ),
        source_page=12,
    ),
    PlanSection(
        section_id="2-2-1",
        number="Ⅱ-2-①",
        chapter="Ⅱ",
        title="중장기 비전 및 목표",
        fill_mode="manual",
        writing_guide="비전 및 목표의 주요 내용, 연차별 또는 단계별 목표의 내용.",
        evaluation_focus="연차별 목표와 추진전략의 현실성, 타당성 등을 파악할 수 있도록 기술.",
        reference_note=(
            "대상기간은 자체 설정. 목표는 정성목표(지표)와 정량목표(지표)를 혼합하여 활용 가능. "
            "소제목(중장기 비전 및 목표, 추진전략 및 세부추진계획)을 통합하여 기술 가능."
        ),
        source_page=13,
    ),
    PlanSection(
        section_id="2-2-2",
        number="Ⅱ-2-②",
        chapter="Ⅱ",
        title="추진 전략 및 세부추진 계획",
        fill_mode="manual",
        writing_guide=(
            "추진전략별 핵심내용, 추진전략별 정성 및 정량 목표, 추진전략별 기금사업 내역 및 "
            "연계사업 내역, 기금사업 우선순위 도출 근거와 과정, 추진전략의 연차별 로드맵, "
            "추진전략 및 기금사업이 비전 및 목표 달성에 기여하는 정도와 예상 근거, "
            "기금사업 간 연계방안 등 기술. 지역 내 거점 및 중점분야를 선정하여 기술."
        ),
        evaluation_focus=(
            "연차별 목표와 추진전략의 현실성·타당성, 계획과 목표가 부합되는 정도, "
            "목표 달성에 대한 기여 정도의 현실성, 기금사업 간 연계성 분석 및 연계방안의 타당성을 기술."
        ),
        reference_note="추진전략별 기금사업명은 'Ⅲ. 기금사업'의 기금사업명과 일치해야 함.",
        source_page=14,
    ),
    PlanSection(
        section_id="2-2-3",
        number="Ⅱ-2-③",
        chapter="Ⅱ",
        title="'26년 기금사업과 인구감소지역대응 기본계획의 연계성",
        fill_mode="manual",
        writing_guide=(
            "인구감소지역 대응 기본계획(5개년)의 전략(과제) 및 실천과제와의 연계성. "
            "'26년 기금사업의 사업명을 작성하고, 연계되는 기본계획의 사업명과 사업내용을 상세히 기술. "
            "※ 관심지역은 작성 제외."
        ),
        evaluation_focus=(
            "인구감소지역 대응 기본계획과 기금사업 간 연계 타당성을 파악. "
            "사업목적, 사업대상(청년, 노인 등) 및 사업내용을 기술하고 해당 페이지를 기입."
        ),
        reference_note="기본계획 5개년 자료가 변경된 경우 별도 제출(인구감소지역대응위원회 심의를 거친 경우만 인정).",
        source_page=15,
        required=False,
    ),
    # ── Ⅲ. 기금사업 ──────────────────────────────────────────
    PlanSection(
        section_id="3-1",
        number="Ⅲ-1",
        chapter="Ⅲ",
        title="추진 배경 및 목적",
        fill_mode="assisted",
        writing_guide=(
            "기금 투자계획 사업 중 중규모의 다년도 중점사업을 선정하여 추진배경 및 사업내용"
            "(사업목표, 주요내용, 기대효과 등)을 작성. "
            "※ 인구감소지역은 중점사업으로 총사업비 200억원 이상 사업을 권장."
        ),
        evaluation_focus=(
            "기반시설 활용 여부와 관계없이 지방소멸 방지와 지역활력 제고를 위한 소프트웨어 사업도 "
            "전반적으로 허용(인건비, 소모성 경비, 현금성 지원 등 제외). "
            "다년도(2~3년) 중점사업을 제출하여야 우수 지자체로 선정 가능."
        ),
        reference_note="사업의 즉시 추진 가능성을 증빙할 수 있는 부지확보 현황, 사전 행정절차 진행 여부 등 포함 가능.",
        source_page=17,
    ),
    PlanSection(
        section_id="3-2",
        number="Ⅲ-2",
        chapter="Ⅲ",
        title="사업 개요 (사업기간·규모·대상지, 부지확보 및 민원, 거점현황)",
        fill_mode="manual",
        writing_guide=(
            "사업기간, 규모(예산), 행정구역 내 기금사업 및 타 연계사업 대상지 위치, "
            "거점 선정 이유 및 근거, 사업대상지 검토사항, 거점현황, 타 사업과의 연계성 등 기술. "
            "사업에 부지가 필요한 경우 부지확보 현황 또는 계획, 토지이용계획, "
            "민원 발생 여부 및 쟁점사항 해결방안을 작성. "
            "※ 부지가 필요한 사업은 부지확보 여부를 반드시 작성."
        ),
        evaluation_focus="사업의 실현 가능성, 대상지나 거점 선정의 타당성 등 기술.",
        reference_note="위치도, 지형도 등 활용 가능. 부지확보 관련 증빙자료는 반드시 제출.",
        source_page=18,
    ),
    PlanSection(
        section_id="3-3",
        number="Ⅲ-3",
        chapter="Ⅲ",
        title="사업 목표",
        fill_mode="assisted",
        writing_guide=(
            "사업목표의 구분(정량/정성)과 내용, 측정방법, 연차별 목표값 등 작성. "
            "사업목표 지표의 적절성, 측정방법의 객관성, 연차별 목표의 적절성을 별도 작성."
        ),
        evaluation_focus="연차별 목표의 현실성과 타당성을 파악할 수 있도록 기술.",
        reference_note=(
            "해당 사업과 직접적으로 연관이 있는 사업목표 선정. "
            "단순 실적지표(예: 예산 집행률)가 아닌 사업의 성과에 해당하는 목표 선정. "
            "사업목표의 현실성(달성 가능성), 측정방법의 객관성 및 측정 가능성 등 고려. "
            "제출한 사업목표는 추후 성과분석 지표와 연동."
        ),
        source_page=19,
    ),
    PlanSection(
        section_id="3-4-1",
        number="Ⅲ-4-①",
        chapter="Ⅲ",
        title="그간 추진상황",
        fill_mode="assisted",
        writing_guide="사업을 추진한 내용이 있을 시 작성하되, 계속사업의 경우는 반드시 작성.",
        evaluation_focus="계속사업은 기존 사업계획에 따른 추진경과를 파악할 수 있도록 기술.",
        reference_note=(
            "신규사업인 경우 사업추진을 위한 선제적 노력의 진행상황 등을 작성. "
            "계속사업인 경우 기존 사업계획에 따른 추진경과 등을 작성."
        ),
        source_page=20,
    ),
    PlanSection(
        section_id="3-4-2",
        number="Ⅲ-4-②",
        chapter="Ⅲ",
        title="사업 추진내용",
        fill_mode="manual",
        writing_guide=(
            "사업의 성격·특성·분야·종류 등을 고려하여 사업의 주요내용을 파악할 수 있는 항목 위주로 기술"
            "(사업 구성·운영방안, 사업 수행방식, 설비·장비 등의 내역 및 활용, 사업 추진과정, "
            "인력 확보 및 활용계획, 소요예산 산출내역 등)."
        ),
        evaluation_focus="사업의 실현 가능성을 파악할 수 있도록 기술.",
        reference_note="추진시기(월별), 시기별 추진내용, 소요예산(백만원) 표 형태 작성 예시 참고.",
        source_page=20,
    ),
    PlanSection(
        section_id="3-4-3",
        number="Ⅲ-4-③",
        chapter="Ⅲ",
        title="사업 추진 체계",
        fill_mode="manual",
        writing_guide=(
            "사업 추진주체 선정 이유와 근거, 추진조직, 관리 및 감독체계, 사업담당자 현황, "
            "역할 분담 내역, 사업추진 관련 지침이나 가이드라인 마련계획 및 내용, "
            "주민참여 보장을 위한 제도나 계획 등 기술."
        ),
        evaluation_focus="사업의 실현 가능성을 파악할 수 있도록 기술.",
        reference_note="그림이나 도표 등 활용 가능.",
        source_page=21,
    ),
    PlanSection(
        section_id="3-4-4",
        number="Ⅲ-4-④",
        chapter="Ⅲ",
        title="사업의 기대효과",
        fill_mode="manual",
        writing_guide=(
            "사업목표 달성을 통한 정성적 기대효과, 재원 및 인력 등 자원 투입 대비 효과의 우수성, "
            "주민참여나 대상자 확대방안, 비용절감 등 효과 극대화 방안 등을 확인할 수 있는 항목 위주로 기술."
        ),
        evaluation_focus="사업의 효과성 및 효율성을 파악할 수 있도록 기술.",
        reference_note="실제 사업성과와 관련하여 경제적 기대효과(소득 및 일자리 창출 등) 기술도 가능.",
        source_page=21,
    ),
    PlanSection(
        section_id="3-4-5",
        number="Ⅲ-4-⑤",
        chapter="Ⅲ",
        title="규모 및 재원 배분계획",
        fill_mode="manual",
        writing_guide=(
            "연차별 재원 투입규모, 재원 구성, '26년 예산 세부내역 등을 작성. "
            "연도별 예산현황(기금 소계-기초계정·광역계정, 국비, 지방비 소계-시도비·시군구비, 기타(민자 등))과 "
            "2026년 재원별 예산 세부내역을 표로 작성."
        ),
        evaluation_focus=(
            "재원 확보방안 등 사업의 실현 가능성 및 재원 투입계획의 적절성을 파악할 수 있도록 기술. "
            "2026년 재원별 예산 세부내역은 기금 투입의 적절성을 파악할 수 있도록 세부적으로 작성."
        ),
        reference_note="재원 확보방안 및 재원 투입규모의 산출내역에 대한 구체적 근거자료 포함 가능.",
        source_page=22,
    ),
    PlanSection(
        section_id="3-5",
        number="Ⅲ-5",
        chapter="Ⅲ",
        title="사업 추진을 위한 사전 절차이행 (관련 법령, 상위 계획과의 검토)",
        fill_mode="manual",
        writing_guide=(
            "관련 법령·상위계획과의 정합성, 관련 법령·상위계획에 규정된 사전절차 검토 및 이행 여부 등 기술"
            "(주민설명회 및 공청회, 현장설명회, 타당성조사, 투자심사, 기본계획 설계, 공유재산관리계획 등). "
            "구분·이행여부·추진기간·추진대책·소관기관 표로 작성."
        ),
        evaluation_focus="사업의 실현 가능성을 파악할 수 있도록 기술.",
        reference_note="타당성조사, 중앙투자심사, 기본계획(설계), 실시계획(설계), 개발행위허가, 농지전용협의, 공유재산관리계획, 군관리계획 변경, 교통영향평가, BF인증, 주민설명회 등.",
        source_page=23,
    ),
    PlanSection(
        section_id="3-annex",
        number="Ⅲ-별첨",
        chapter="Ⅲ",
        title="부적정 사업 대상 여부 진단 체크리스트",
        fill_mode="assisted",
        writing_guide=(
            "기금사업별로 아래 항목의 해당 여부(여/부)를 작성한다. "
            "1. 지방소멸대응기금 사업의 목적에 현저히 위배되는 사업이 포함되었는지? "
            "2. 국고보조사업의 지방비 매칭 부담액으로 기금이 사용되었는지? "
            "3. 인건비, 경상비 등 소모성 경비에 기금이 사용되었는지? "
            "3-1. 결혼지원금, 출산장려금, 장학금, 숙박권 등 현금성 지원사업에 기금이 사용되었는지? "
            "3-2. 해외 어학연수 등 외유성 경비에 기금이 사용되었는지? "
            "4. 공공청사 확충 등 지역 내 거점의 생활인프라 조성과 직접적으로 관련이 없는 사업인지? "
            "5. 부지매입비가 기금 예산에 포함되었는지?"
        ),
        evaluation_focus="기금 투자 제외 대상 사업(안내서 p.5)에 해당하지 않음을 자체 점검하여 확인.",
        reference_note="기금사업별 작성.",
        source_page=24,
    ),
    # ── Ⅳ. 타 재정·정책 연계방안 (전체 manual) ──────────────────
    PlanSection(
        section_id="4-1",
        number="Ⅳ-1",
        chapter="Ⅳ",
        title="타 사업·정책과 연계방안 개요",
        fill_mode="manual",
        writing_guide=(
            "전체 기금사업의 연계효과를 극대화하기 위한 방안과 계획을 확인할 수 있는 항목 위주로 기술"
            "(예산배분 조정계획, 연관 사업계획 조정계획, 연계를 위한 담당업무 조정계획, "
            "관련 조례 정비계획, 협력체계 구축계획, 연계방안의 구체적인 사례나 예시 등)."
        ),
        evaluation_focus="연계효과를 극대화하기 위한 방안과 계획의 적절성 등 기술.",
        reference_note="그림이나 도표 등 활용 가능.",
        source_page=26,
    ),
    PlanSection(
        section_id="4-2",
        number="Ⅳ-2",
        chapter="Ⅳ",
        title="주요 연계 타 사업·정책 내역",
        fill_mode="manual",
        writing_guide=(
            "기금사업별 연계사업명, 주요내용, 예산, 연계의 내용 및 연계를 통한 기대효과 등을 작성. "
            "우선순위 / 기금사업명(예산) / 연계사업명(관계부처·지자체·민간) / 연계사업 주요내용 / "
            "연계사업 예산(확정예산) / 연계내용 및 기대효과 표 형태."
        ),
        evaluation_focus="사업 간 연계성 분석의 적절성을 파악할 수 있도록 연계의 내용 및 기대효과 기술.",
        reference_note="국고보조사업, 지자체사업, 민간투자사업, 업무협약, 투자협약 등 확정된 건에 대해 기재.",
        source_page=27,
    ),
    PlanSection(
        section_id="4-3",
        number="Ⅳ-3",
        chapter="Ⅳ",
        title="타 지자체와 연계방안",
        fill_mode="manual",
        writing_guide=(
            "타 지자체와 연계의 배경 및 필요성, 연계목적, 연계를 위한 사전준비와 논의과정, "
            "연계계획, 연계방안의 구체적 내용, 연계의 기대효과, 향후 추진계획 등 기술."
        ),
        evaluation_focus=(
            "타 지자체와 연계를 위해 효과적이고 구체적인 노력과 계획을 파악할 수 있도록 기술. "
            "연계의 효과나 성과의 우수성을 파악할 수 있도록 기술."
        ),
        reference_note="그림이나 도표 등 활용 가능.",
        source_page=28,
        required=False,
    ),
    # ── Ⅴ. 운영 및 관리체계 (전체 manual) ───────────────────────
    PlanSection(
        section_id="5-1-1",
        number="Ⅴ-1-①",
        chapter="Ⅴ",
        title="투자계획 조직 구성",
        fill_mode="manual",
        writing_guide=(
            "투자계획 및 추진, 운영, 관리 등을 위한 참여주체(총괄책임자, 유관부서·기관, 각종 위원회, "
            "기업, 민간기관, 시민단체, 주민 등)와 조직 구성현황을 구체적(구성일자 등)으로 기술."
        ),
        evaluation_focus="투자계획 조직 구성의 적절성을 알 수 있도록 구체적으로 조직체계 기술.",
        reference_note="내부조직과 외부조직을 하나의 조직체계에 포함하여 제시 가능.",
        source_page=29,
    ),
    PlanSection(
        section_id="5-1-2",
        number="Ⅴ-1-②",
        chapter="Ⅴ",
        title="투자계획 조직 운영",
        fill_mode="manual",
        writing_guide=(
            "조직 운영현황, 운영 및 관리를 위한 관련 조례현황(조례내용, 조례 제·개정계획 등), "
            "조직 참여주체별 주요기능 및 운영방안, 참여주체별 역할, 조직 운영을 위한 지침이나 "
            "가이드라인 현황 또는 내용, 주민참여를 보장하는 운영방안 등을 구체적으로 기술."
        ),
        evaluation_focus="투자계획 조직 운영의 적절성을 파악할 수 있도록 실제 운영현황 중심으로 구체적으로 기술.",
        reference_note="내부조직과 외부조직 운영계획을 통합하여 기술 가능.",
        source_page=30,
    ),
    PlanSection(
        section_id="5-2-1",
        number="Ⅴ-2-①",
        chapter="Ⅴ",
        title="성과관리 체계 구축",
        fill_mode="manual",
        writing_guide=(
            "투자계획 및 개별 기금사업 성과관리 책임자, 부서, 과정, 주민참여체계 등 "
            "성과관리를 위한 체계 현황 또는 구성계획 기술."
        ),
        evaluation_focus="성과관리 체계의 적절성을 파악할 수 있도록 조직현황 또는 구성계획을 구체적으로 기술.",
        reference_note="그림이나 도표 등 활용 가능.",
        source_page=31,
    ),
    PlanSection(
        section_id="5-2-2",
        number="Ⅴ-2-②",
        chapter="Ⅴ",
        title="성과관리 체계 운영",
        fill_mode="manual",
        writing_guide=(
            "성과관리 체계 운영을 위한 각종 지침 등의 현황 또는 추진계획, 성과관리 과정 및 방법, "
            "성과확산 방안, 환류 및 개선체계 등 기술."
        ),
        evaluation_focus="성과관리 체계 운영의 적절성을 파악할 수 있도록 실제 운영현황 또는 운영계획을 구체적으로 기술.",
        reference_note="투자계획 전체에 대한 성과관리 운영계획 기술. 기금사업별 운영계획 기술 가능(필요한 경우에 한함).",
        source_page=32,
    ),
    PlanSection(
        section_id="5-3",
        number="Ⅴ-3",
        chapter="Ⅴ",
        title="사후 관리체계",
        fill_mode="manual",
        writing_guide=(
            "투자계획 및 개별 기금사업 완료 후 관리방법 및 운영방향, 시설 유지관리 방안, "
            "운영 및 관리주체, 추가 사업계획 및 프로그램 개발계획, 예산 조달계획 등 기술."
        ),
        evaluation_focus="사후 관리체계의 지속성을 파악할 수 있도록 기술. 사후관리 방안의 지속성, 현실성, 적절성 기술.",
        reference_note="그림이나 도표 등 활용 가능.",
        source_page=33,
    ),
    # ── Ⅵ. 기타 ─────────────────────────────────────────────
    PlanSection(
        section_id="6-1",
        number="Ⅵ-1",
        chapter="Ⅵ",
        title="전체 사업예산",
        fill_mode="manual",
        writing_guide=(
            "[기금사업] 중점사업과 우선순위 사업비를 구분하여 작성. "
            "[연계사업] 공모 선정 완료, 다년도 계속사업, 업무협약, 투자협약 등 확정예산을 기재. "
            "구분별(지방소멸대응기금사업 / 국고보조사업 / 지자체 자체사업) × 연도별(’22~’25년, 2026년, "
            "2027년, 2028년, 2029년 이후, 합계) 표. 단위: 백만원."
        ),
        evaluation_focus="전체 재원 구성과 연차별 투입 규모를 확인할 수 있도록 작성.",
        reference_note="기금은 기초계정·광역계정을 구분하고, 지방비는 시도비·시군구비를 구분한다.",
        source_page=34,
    ),
    PlanSection(
        section_id="6-2-1",
        number="Ⅵ-2-①",
        chapter="Ⅵ",
        title="연도별 기금사업 추진 성과표",
        fill_mode="auto",
        writing_guide=(
            "연도별(’22년/’23년/’24년) 기금사업의 배분액·집행액·집행률(%)과 사업별 완료/추진중 여부를 작성. "
            "단위: 백만원. 부진 사유 등 기재(별첨 가능)."
        ),
        evaluation_focus="'22~'24년 기금사업 추진실적 및 성과는 1차 평가에 반영(가점 4점).",
        reference_note="사업 구분 / 배분액 / 집행액 / 집행률(%) / (완료·추진중) / 비고 표 형태.",
        source_page=35,
        manual_remainder=(
            "서버는 연도별 소계(배분액·집행액·집행률)만 채운다. 우리 패널이 지역-연도 단위라 "
            "사업 단위로 분해할 수 없기 때문이다. 사업별 행(사업명·배분액·집행액·완료 여부)은 담당자가 작성한다."
        ),
    ),
    PlanSection(
        section_id="6-2-2",
        number="Ⅵ-2-②",
        chapter="Ⅵ",
        title="연도별 기금사업 추진 현황",
        fill_mode="manual",
        writing_guide=(
            "연도별로 사업마다 담당부서(운영주체), 기금 집행률(완료/추진중), 사업개요"
            "(사업기간, 총사업비 및 재원별 내역, 사업내용), 추진실적 및 성과를 작성. "
            "성과가 저조한 경우 해당 사유를 작성하는 것도 가능."
        ),
        evaluation_focus="추진실적과 성과 점검을 통해 향후 기금 투자계획의 방향성을 확인할 수 있도록 작성.",
        reference_note="'25년 6월말 기준으로 작성.",
        source_page=36,
    ),
)

SECTION_BY_ID: dict[str, PlanSection] = {s.section_id: s for s in SECTIONS}

AUTO_SECTIONS = tuple(s.section_id for s in SECTIONS if s.fill_mode == "auto")
ASSISTED_SECTIONS = tuple(s.section_id for s in SECTIONS if s.fill_mode == "assisted")
MANUAL_SECTIONS = tuple(s.section_id for s in SECTIONS if s.fill_mode == "manual")


def get_section(section_id: str) -> PlanSection:
    from app.errors import ApiError

    section = SECTION_BY_ID.get(section_id)
    if section is None:
        raise ApiError(
            status_code=404,
            code="unknown_section",
            message=f"'{section_id}' 는 서식에 없는 섹션입니다.",
            field="section_id",
            allowed_values=list(SECTION_BY_ID),
        )
    return section


def sections_of_chapter(chapter: str) -> list[PlanSection]:
    return [s for s in SECTIONS if s.chapter == chapter]
