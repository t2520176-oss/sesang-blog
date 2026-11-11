"""AI(무료 Gemini 또는 Claude)로 블로그 글(제목 + 본문 블록 + 태그)을 만든다."""
import json

import anthropic
import requests

MODEL = "claude-opus-5-5"

# 글 종류 3가지 (홈판용 / 검색용 / 브랜드)
MODES = {
    "home": {
        "label": "홈판용 글",
        "desc": "관심을 끄는 이야기",
        "guide": (
            "네이버 블로그 홈 피드에 노출될 글. 첫 문단에서 호기심을 끌고, "
            "개인 경험담처럼 친근한 구어체(~했어요, ~더라고요)로 쓴다. "
            "소제목 3~5개, 공감 가는 에피소드와 솔직한 느낌을 담는다."
        ),
    },
    "search": {
        "label": "검색용 글",
        "desc": "궁금한 점에 답하기",
        "guide": (
            "검색으로 들어온 사람이 궁금한 점을 바로 해결하도록 쓰는 정보성 글. "
            "제목과 첫 문단에 핵심 키워드를 자연스럽게 넣고, 소제목마다 질문 하나에 답한다. "
            "정확하지 않은 수치·날짜는 지어내지 말고, 확인이 필요한 부분은 확인을 권한다. "
            "마지막에 핵심 요약을 둔다."
        ),
    },
    "brand": {
        "label": "브랜드 글",
        "desc": "내 사업·상품 알리기",
        "guide": (
            "아래 '브랜드 정보'의 사업/상품을 자연스럽게 소개하는 글. 과장 광고나 "
            "검증 안 된 효능 주장은 하지 않는다. 고객이 겪는 문제 → 해결 방법 → 브랜드 소개 → "
            "이용 방법 순서로 쓰고, 끝에 부드러운 행동 유도 문장을 넣는다."
        ),
    },
}

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "title_options": {"type": "array", "items": {"type": "string"}},
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["heading", "paragraph", "quote", "image"]},
                    "text": {"type": "string"},
                    "caption": {"type": "string"},
                },
                "required": ["type", "text"],
                "additionalProperties": False,
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "title_options", "blocks", "tags"],
    "additionalProperties": False,
}

BASE = (
    "너는 네이버 블로그 글을 쓰는 한국어 작가다. 사람이 직접 쓴 것처럼 자연스럽게 쓰고, "
    "AI가 쓴 티가 나는 상투어(예: '결론적으로', '다양한', '~에 대해 알아보겠습니다')는 피한다. "
    "마크다운 기호(#, **, -)는 쓰지 않는다. 태그는 # 없이 5~10개.\n"
    "제목은 항상 '후킹 제목'으로 짓는다 (25~38자):\n"
    "- 핵심 검색 키워드(인물·사건·상품 이름)를 제목 앞쪽에 둔다\n"
    "- 궁금증을 남긴다: 질문형(~은?, ~일까?), 반전·의외성(알고 보니, 결국, 사실이었다), "
    "숫자(3가지, 7분의 1), 말줄임(…)이나 가운뎃점(·)으로 뒷이야기 예고\n"
    "- 본문에서 실제로 답하는 내용만 약속한다. 본문에 없는 사실, 과장, 낚시성 거짓은 금지\n"
    "- title 에는 가장 강한 1개, title_options 에는 다른 각도의 후킹 제목 3개를 넣는다\n"
)
NATURAL = (
    "문단은 2~4문장으로 짧게 끊는다. "
    "자연스럽게 쓰는 법: 문장 길이를 섞고(짧은 문장도 넣기), 내가 직접 보고 느낀 것처럼 한두 마디 "
    "감상을 넣고, 목록처럼 딱딱하게 나열하지 말고 이야기 흐름으로 잇는다. 소제목은 질문형이나 "
    "말하듯이 짓는다. 끝은 요약 대신 독자에게 건네는 한마디로 마무리한다."
)
STYLE = (
    "아래 <내글> 은 이 블로그 주인이 실제로 쓴 글이다. 이 사람이 쓴 것처럼 문체를 그대로 따라 쓴다:\n"
    "- 어미·말투(예: ~습니다, ~는데요, ~걸까요?), 존댓말 수준\n"
    "- 문단 길이(한 문단에 몇 문장인지)와 문단을 끊는 위치\n"
    "- 다음 내용으로 넘어갈 때 쓰는 질문·연결 문장\n"
    "- 제목을 짓는 방식(질문형, 가운뎃점 · 으로 키워드 나열 등)과 제목 바로 아래 한 줄 요약 문장\n"
    "- 사실 전달 표현(~것으로 알려졌습니다, ~라고 밝혔습니다)과 개인 감상의 양\n"
    "'글 종류' 지침과 문체가 다르면 <내글> 문체를 따른다. "
    "<내글> 의 내용·사실·인물은 절대 가져오지 않는다. 문체만 따른다. "
    "제목 아래 한 줄 요약 문장이 있으면 그것은 첫 블록(type heading)으로 쓴다.\n"
)


def system_prompt(style_sample: str = "") -> str:
    s = (style_sample or "").strip()
    if not s:
        return BASE + NATURAL
    return BASE + STYLE + "<내글>\n" + s[:4000] + "\n</내글>"


SYSTEM = system_prompt()

IMAGE_GUIDE = (
    "\n사진 넣기: 본문 중간에 type 'image' 블록을 {n}개 넣는다. 첫 사진은 첫 문단 바로 뒤, "
    "나머지는 소제목 내용 사이사이에 고르게. image 블록의 text 는 사진 검색어(영어 2~4단어, "
    "구체적 사물/장소/장면, 사람 얼굴·로고·상표는 피함), caption 은 사진 아래 붙일 자연스러운 "
    "한국어 한 줄(15자 안팎, 예: '오늘 들른 동네 약국 풍경'). 실존 인물 사진은 넣지 않는다.\n"
)


def generate_post(api_key: str, topic: str, mode: str = "home", length: int = 1500,
                  brand_info: str = "", extra: str = "", news: list = None,
                  photos: int = 0, style: str = "") -> dict:
    """{'title': str, 'blocks': [{'type','text'}], 'tags': [str]} 를 돌려준다."""
    m = MODES[mode]
    prompt = (
        f"주제: {topic}\n"
        f"글 종류: {m['label']} - {m['guide']}\n"
        f"분량: 본문 약 {length}자\n"
    )
    if mode == "brand" and brand_info.strip():
        prompt += f"\n브랜드 정보:\n{brand_info.strip()}\n"
    if news:
        heads = "\n".join(f"- {n['title']} ({n['source']})" for n in news if n.get("title"))
        prompt += (
            "\n지금 화제인 이슈다. 관련 뉴스 제목:\n" + heads + "\n"
            "위 제목에서 확인되는 사실만 쓰고, 제목에 없는 수치·발언·결과는 지어내지 않는다. "
            "확실하지 않은 부분은 '~로 알려졌다', '자세한 내용은 기사에서 확인'처럼 쓴다. "
            "독자가 이 이슈를 왜 찾아보는지, 알아두면 좋은 배경을 중심으로 쓴다.\n"
        )
    if photos > 0:
        prompt += IMAGE_GUIDE.format(n=photos)
    if extra.strip():
        prompt += f"\n추가 요청:\n{extra.strip()}\n"

    api_key = (api_key or "").strip()
    if not api_key.startswith("sk-ant"):
        post = _gemini(api_key, prompt, system_prompt(style))   # 무료 (Google AI Studio 키)
    else:
        post = _claude(api_key, prompt, system_prompt(style))   # 유료 (Anthropic 키)
    post["tags"] = [t.lstrip("#").strip() for t in post.get("tags", []) if t.strip()][:10]
    post["blocks"] = [b for b in post.get("blocks", []) if b.get("text", "").strip()
                      and (photos > 0 or b.get("type") != "image")][:80]
    if not post.get("title") or not post["blocks"]:
        raise RuntimeError("AI 응답이 비어 있습니다. 다시 시도해 주세요.")
    return post


# ---- Google Gemini (무료 등급) -------------------------------------------
GEMINI_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]   # 앞 모델 한도 초과 시 다음 모델
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "title_options": {"type": "ARRAY", "items": {"type": "STRING"}},
        "blocks": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"type": {"type": "STRING", "enum": ["heading", "paragraph", "quote", "image"]},
                           "text": {"type": "STRING"}, "caption": {"type": "STRING"}},
            "required": ["type", "text"]}},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "title_options", "blocks", "tags"],
}


def _gemini(api_key, prompt, system=SYSTEM):
    if not api_key:
        raise RuntimeError("AI 키가 없습니다. aistudio.google.com/apikey 에서 무료 키를 받아 넣으세요.")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "responseSchema": GEMINI_SCHEMA, "maxOutputTokens": 16000},
    }
    last = ""
    for model in GEMINI_MODELS:
        try:
            r = requests.post(GEMINI_URL.format(model), json=body, timeout=(15, 120),
                              headers={"x-goog-api-key": api_key})
        except (requests.Timeout, requests.ConnectionError) as e:   # 응답 지연 -> 다음 모델
            last = f"{model}: 응답 없음 ({type(e).__name__})"
            continue
        if r.status_code in (429, 404, 500, 503):        # 무료 한도 초과/모델 없음/혼잡 -> 다음 모델
            last = f"{model}: {r.status_code} {r.text[:200]}"
            continue
        if r.status_code in (400, 401, 403):
            raise RuntimeError(f"Gemini 키 오류 ({r.status_code}). 키를 확인하세요: {r.text[:200]}")
        r.raise_for_status()
        data = r.json()
        cands = data.get("candidates") or []
        if not cands:
            raise RuntimeError(f"AI가 이 주제로 글을 쓰지 않았습니다. 주제를 바꿔 주세요. "
                               f"({data.get('promptFeedback', {})})")
        c = cands[0]
        if c.get("finishReason") == "MAX_TOKENS":
            raise RuntimeError("글이 너무 길어 중간에 끊겼습니다. 분량을 줄여 주세요.")
        text = "".join(p.get("text", "") for p in c.get("content", {}).get("parts", [])
                       if not p.get("thought"))
        return json.loads(text)
    raise RuntimeError("오늘 무료 사용량을 다 썼거나 서버가 바쁩니다. 잠시 후(또는 내일) 다시 시도하세요. " + last)


# ---- Anthropic Claude (유료) ---------------------------------------------
def _claude(api_key, prompt, system=SYSTEM):
    client = anthropic.Anthropic(api_key=api_key)
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=16000,
        system=system,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        resp = stream.get_final_message()

    if resp.stop_reason == "refusal":
        raise RuntimeError("AI가 이 주제의 글 작성을 거절했습니다. 주제를 바꿔 주세요.")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("글이 너무 길어 중간에 끊겼습니다. 분량을 줄여 주세요.")
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def post_to_text(post: dict) -> str:
    """미리보기/편집용 평문. 소제목은 [소제목], 인용은 > 로 표시."""
    out = []
    for b in post["blocks"]:
        if b["type"] == "image":
            out.append(f"[사진] {b['text']} | {b.get('caption', '')}")
        elif b["type"] == "heading":
            out.append(f"[소제목] {b['text']}")
        elif b["type"] == "quote":
            out.append(f"> {b['text']}")
        else:
            out.append(b["text"])
    return "\n\n".join(out)


def text_to_blocks(text: str) -> list:
    """편집한 평문을 다시 블록으로."""
    blocks = []
    for chunk in [c.strip() for c in text.replace("\r\n", "\n").split("\n\n")]:
        if not chunk:
            continue
        if chunk.startswith("[사진]"):
            q, _, cap = chunk[len("[사진]"):].partition("|")
            blocks.append({"type": "image", "text": q.strip(), "caption": cap.strip()})
        elif chunk.startswith("[소제목]"):
            blocks.append({"type": "heading", "text": chunk[len("[소제목]"):].strip()})
        elif chunk.startswith(">"):
            blocks.append({"type": "quote", "text": chunk.lstrip("> ").strip()})
        else:
            blocks.append({"type": "paragraph", "text": chunk})
    return blocks
