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
    fails = []
    if d["routing"]["router"] != "llm":
        fails.append("router!=llm (LLM 라우팅 폴백됨)")
    if not d["numeric_guard"]["passed"]:
        fails.append("numeric_guard 실패")
    if d["narrator"] != "llm":
        fails.append("narrator!=llm (서술 폴백됨)")
    if "intent" in case and d["routing"]["intent"] != case["intent"]:
        fails.append(f"intent={d['routing']['intent']} (기대 {case['intent']})")
    if "regions" in case and set(d["routing"]["regions"]) != set(case["regions"]):
        fails.append(f"regions={d['routing']['regions']} (기대 {case['regions']})")
    for kw in case.get("answer_contains", []):
        if kw not in d["answer"]:
            fails.append(f"답변에 '{kw}' 없음")
    return fails


def main():
    cases = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    passed = 0
    for c in cases:
        try:
            d = chat(c["question"])
        except Exception as e:
            print(f"[에러] {c['question']}  ->  {e}")
            continue
        fails = check(c, d)
        if fails:
            print(f"[FAIL] {c['question']}")
            for f in fails:
                print(f"        - {f}")
        else:
            passed += 1
            print(f"[ ok ] {c['question']}")
        print(f"        답변: {d['answer'][:70]}...")
    print(f"\n===== {passed}/{len(cases)} 통과 =====")


if __name__ == "__main__":
    main()
