"""Explainable, local screening of untrusted meeting-note text."""

from dataclasses import dataclass
import re


RULESET_VERSION = "input-risk-v1"
WARN_AT = 30
HOLD_AT = 70
MAX_SPANS_PER_RULE = 3
# Match related cues in the same clause while preserving offsets in the original text.
NEAR = r"[^.!?。！？\r\n]{0,40}?"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    reason: str
    points: int
    pattern: re.Pattern[str]


RULES = (
    Rule(
        "task_override", "기존 요청을 무시하거나 문서 지시를 우선하라는 표현", 50,
        re.compile(
            r"(?:앞의|이전|기존|원래)\s*(?:지시|요청|규칙)(?:을|를)?\s*무시"
            r"|요약하지\s*(?:말|마)"
            r"|(?:문서|본문)(?:의)?\s*지시(?:를)?\s*최우선"
            r"|\b(?:ignore|disregard)\s+(?:the\s+)?(?:previous|prior|original)\s+(?:instructions?|requests?)\b",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "authority_claim", "문서 안에 상위 역할이나 관리자 지시 표기가 있음", 25,
        re.compile(
            r"<\s*(?:system|developer)\s*>|(?:시스템|관리자)\s*(?:지시|명령)\s*[:：]",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "forced_output", "응답을 특정 문구로 쓰거나 바꾸도록 요구하는 표현", 35,
        re.compile(
            rf"(?:답변|응답|요약\s*결과){NEAR}(?:로만\s*(?:작성|출력|답)|로\s*(?:바꿔|바꾸|변경|대체))"
            r"|\b(?:reply|respond|output)\s+only\b", re.IGNORECASE,
        ),
    ),
    Rule(
        "private_data_request", "비공개 자료를 읽거나 요약에 포함하라는 표현", 70,
        re.compile(
            rf"(?:비공개|기밀)\s*(?:메모|문서|자료|파일|정보){NEAR}"
            rf"(?:(?:요약|답변|응답){NEAR}(?:포함|출력|노출)|(?:읽어|열어|보여))"
            r"|\b(?:read|reveal|disclose)\s+(?:the\s+)?(?:private|confidential)\s+(?:notes?|files?|documents?)\b",
            re.IGNORECASE,
        ),
    ),
    Rule(
        "external_transfer", "파일이나 문서를 외부로 보내는 동작을 지칭하는 표현", 70,
        re.compile(
            rf"외부{NEAR}(?:파일|자료|문서|요약){NEAR}(?:전송|송신|보내)"
            rf"|(?:파일|자료|문서|요약)(?:을|를){NEAR}외부(?:로|에){NEAR}(?:전송|송신|보내)"
            rf"|\b(?:send|transfer|upload)\b{NEAR}\b(?:files?|documents?|summary)\b{NEAR}\bexternal\b",
            re.IGNORECASE,
        ),
    ),
)


def decision_for_score(score: int) -> str:
    if score >= HOLD_AT:
        return "hold"
    if score >= WARN_AT:
        return "warn"
    return "proceed"


def assess_input(document: str) -> dict:
    """Score each distinct rule once and report original Unicode character offsets."""
    if not isinstance(document, str) or not document.strip():
        raise ValueError("document must be a non-empty string")
    findings = []
    score = 0
    for rule in RULES:
        spans = []
        match_count = 0
        for match in rule.pattern.finditer(document):
            match_count += 1
            if len(spans) < MAX_SPANS_PER_RULE:
                spans.append({"start": match.start(), "end": match.end(), "text": match.group()})
        if match_count:
            score += rule.points
            findings.append({
                "rule_id": rule.rule_id, "reason": rule.reason, "points": rule.points,
                "match_count": match_count, "spans": spans,
            })
    score = min(score, 100)
    return {
        "ruleset_version": RULESET_VERSION,
        "score": score,
        "decision": decision_for_score(score),
        "findings": findings,
    }
