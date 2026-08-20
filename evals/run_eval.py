"""경량 LLM 회귀 평가.

서버(localhost:8000)를 띄운 상태에서 실행:
    uv run --no-project python evals/run_eval.py

프롬프트를 고칠 때마다 돌려서 라우팅·서술이 깨지지 않았는지 한눈에 확인한다.
질문 추가는 golden.jsonl 에 한 줄(JSON) 넣으면 된다.
필드: question(필수), intent, regions, answer_contains(답변에 포함돼야 할 문자열들) — 뒤 3개는 선택.
"""
import json
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000"
GOLDEN = Path(__file__).parent / "golden.jsonl"


def chat(question):
    body = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["data"]


def check(case, d):
    """3단계 판정.

    - fails: 진짜 문제. 반드시 고쳐야 한다(의미 오류 + LLM 호출 실패).
    - warns: 설계상 정상인 폴백. numeric_guard가 LLM 서술을 걸러 규칙으로 내려간 경우는
      방어가 제대로 동작한 것이므로 실패로 세지 않는다.

    핵심 구분: narrator 가 llm 이 아닐 때, guard 가 막은 것(guard_fallback)이면 정상(warn),
    그 밖의 이유로 규칙 서술로 떨어졌으면 LLM 호출 실패로 보고 fail 로 센다.
    """
    fails = []
    warns = []

    narrator = d["narrator"]
    router = d["routing"]["router"]
    guard_passed = d["numeric_guard"]["passed"]
    guard_rejected = d["numeric_guard"].get("rejected_numbers") or []

    # 서술 계층 판정
    # - guard_fallback: 규칙 서술조차 검증 실패해 안내문으로 대체됨(설계상 정상 방어)
    # - rules + 걸러진 숫자 있음: LLM 서술을 가드가 막고 규칙으로 내려감(정상 방어)
    # - 그 밖에 narrator!=llm: LLM 호출 자체가 실패한 것으로 보고 진짜 문제로 센다
    if narrator == "guard_fallback" or (narrator == "rules" and guard_rejected):
        warns.append("가드가 LLM 서술을 걸러 규칙으로 내려감(설계상 정상)")
    elif narrator != "llm":
        fails.append(f"narrator={narrator} (LLM 서술 호출 실패로 폴백)")

    # 라우팅 계층 판정: LLM 서술은 정상인데 라우팅만 규칙이면 LLM 라우팅 호출 실패
    if router != "llm" and narrator == "llm":
        fails.append("router!=llm (LLM 라우팅 호출 실패)")

    # 의미 오류: 무조건 진짜 문제
    if "intent" in case and d["routing"]["intent"] != case["intent"]:
        fails.append(f"intent={d['routing']['intent']} (기대 {case['intent']})")
    if "regions" in case and set(d["routing"]["regions"]) != set(case["regions"]):
        fails.append(f"regions={d['routing']['regions']} (기대 {case['regions']})")
    for kw in case.get("answer_contains", []):
        if kw not in d["answer"]:
            fails.append(f"답변에 '{kw}' 없음")

    return fails, warns


def main():
    cases = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    passed = warned = failed = errored = 0
    for c in cases:
        try:
            d = chat(c["question"])
        except Exception as e:
            print(f"[에러] {c['question']}  ->  {e}")
            errored += 1
            continue
        fails, warns = check(c, d)
        if fails:
            failed += 1
            print(f"[FAIL] {c['question']}")
            for f in fails:
                print(f"        - {f}")
        elif warns:
            warned += 1
            print(f"[WARN] {c['question']}")
            for w in warns:
                print(f"        - {w}")
        else:
            passed += 1
            print(f"[ ok ] {c['question']}")
        print(f"        답변: {d['answer'][:70]}...")
    total = len(cases)
    print(f"\n===== PASS {passed} / WARN {warned} / FAIL {failed} / 에러 {errored}  (총 {total}) =====")
    print("  PASS=정상, WARN=설계상 폴백(정상 방어), FAIL=고쳐야 할 진짜 문제")


if __name__ == "__main__":
    main()
