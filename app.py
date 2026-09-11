import io
import os
import json
import base64
import zipfile
from pathlib import Path

import requests
from PIL import Image
import streamlit as st


APP_TITLE = "🎨 LINE Sticker Factory v0.6"
API_BASE = "https://gen.pollinations.ai"
TEXT_MODEL = os.getenv("POLLINATIONS_TEXT_MODEL", "openai")
IMAGE_MODEL = os.getenv("POLLINATIONS_IMAGE_MODEL", "kontext")

SCENARIOS = {
    "上班日常": "職場、工作、上班、疲累、回覆同事、加班、下班等日常。",
    "情侶互動": "情侶之間的撒嬌、想念、關心、道歉、等待、約會與甜蜜互動。",
    "朋友聊天": "朋友聊天、吐槽、安慰、邀約、已讀、驚訝、開心與日常回覆。",
    "搞笑吐槽": "誇張反應、吐槽、崩潰、無言、傻眼、得意、搞笑日常。",
    "可愛撒嬌": "可愛、撒嬌、害羞、求抱抱、想你、謝謝、拜託、晚安等。",
    "生活日常": "吃飯、睡覺、出門、回家、天氣、購物、休息、開心與小情緒。",
    "自訂情境": "",
}

DEFAULT_LINES = [
    "早安",
    "收到！",
    "等一下啦",
    "我懂你",
    "辛苦了",
    "哈哈哈哈",
    "謝謝你",
    "晚安",
]


def get_api_key():
    try:
        return st.secrets["POLLINATIONS_API_KEY"]
    except Exception:
        return os.getenv("POLLINATIONS_API_KEY", "")


def call_text_ai(user_prompt: str):
    key = get_api_key()
    if not key:
        raise RuntimeError("找不到 POLLINATIONS_API_KEY。請在 Streamlit Secrets 設定。")

    payload = {
        "model": TEXT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 LINE 貼圖腳本企劃。"
                    "請使用繁體中文。每格必須短、自然、像聊天訊息。"
                    "不要寫長句，不要加入不必要的旁白。"
                    "輸出嚴格 JSON，格式為 {\"stickers\":[{\"index\":1,\"text\":\"...\","
                    "\"action\":\"...\",\"expression\":\"...\",\"scene\":\"...\"}]}。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
    }
    r = requests.post(
        f"{API_BASE}/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"腳本 AI 回應 {r.status_code}: {r.text[:600]}")
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    return parse_scripts(content)


def parse_scripts(content: str):
    content = content.strip()
    if content.startswith("```"):
        content = content.replace("```json", "").replace("```", "").strip()
    try:
        obj = json.loads(content)
        items = obj.get("stickers", [])
        if items:
            return normalize_scripts(items)
    except Exception:
        pass

    # Fallback: try to locate the JSON object inside extra prose.
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(content[start:end + 1])
            items = obj.get("stickers", [])
            if items:
                return normalize_scripts(items)
        except Exception:
            pass

    # Last fallback: provide editable starter scripts rather than failing the whole app.
    return normalize_scripts([
        {"index": i + 1, "text": DEFAULT_LINES[i % len(DEFAULT_LINES)],
         "action": "自然的聊天動作", "expression": "可愛自然", "scene": "簡潔乾淨背景"}
        for i in range(8)
    ])


def normalize_scripts(items):
    out = []
    for i, item in enumerate(items):
        out.append({
            "index": i + 1,
            "text": str(item.get("text", DEFAULT_LINES[i % len(DEFAULT_LINES)]))[:30],
            "action": str(item.get("action", "自然的聊天動作"))[:80],
            "expression": str(item.get("expression", "可愛自然"))[:50],
            "scene": str(item.get("scene", "簡潔乾淨背景"))[:80],
        })
    return out


def build_script_prompt(scenario_name, scenario_desc, idea, count, character_note):
    return f"""
請根據以下需求，設計 {count} 格 LINE 貼圖腳本。

情境：{scenario_name}
情境補充：{scenario_desc}
使用者的一句話：{idea}
主角設定：{character_note}

規則：
1. 每格是可以直接放在 LINE 貼圖上的繁體中文短台詞，最好 2～10 個字。
2. {count} 格要有明顯不同的情緒、動作或使用時機，不要只是同義改寫。
3. 腳本要像真實聊天會使用的回覆。
4. action 寫主角的肢體動作；expression 寫表情；scene 寫極簡背景。
5. 主角永遠是同一位上傳角色，不新增第二個主要人物。
6. 不要寫圖片生成提示詞，不要寫教學，不要加 Markdown。
7. 嚴格只輸出 JSON。
""".strip()


def image_edit(reference_bytes, prompt):
    key = get_api_key()
    if not key:
        raise RuntimeError("找不到 POLLINATIONS_API_KEY。請在 Streamlit Secrets 設定。")

    files = {
        "image": ("character.png", reference_bytes, "image/png"),
    }
    data = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "size": "1024x1024",
    }
    r = requests.post(
        f"{API_BASE}/v1/images/edits",
        headers={"Authorization": f"Bearer {key}"},
        files=files,
        data=data,
        timeout=240,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"圖片 AI 回應 {r.status_code}: {r.text[:800]}")

    result = r.json()
    item = result.get("data", [{}])[0]

    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])

    if item.get("url"):
        rr = requests.get(
            item["url"],
            headers={"Authorization": f"Bearer {key}"},
            timeout=120,
        )
        rr.raise_for_status()
        return rr.content

    raise RuntimeError("圖片 API 沒有回傳可用的圖片資料。")


def make_image_prompt(script, scenario_name, character_note):
    return f"""
Create ONE LINE sticker image using the uploaded reference character as the same main character.

CHARACTER LOCK:
{character_note}

SCENE:
Scenario: {scenario_name}
Sticker text: "{script['text']}"
Action: {script['action']}
Expression: {script['expression']}
Minimal background: {script['scene']}

VISUAL RULES:
- Keep the uploaded character's identity, hairstyle, glasses, face shape, body proportions and clothing identity consistent.
- Cute chibi sticker illustration, clean readable silhouette, expressive pose.
- ONE main character only. No second person.
- Traditional Chinese sticker text exactly: "{script['text']}"
- Make the text large, clear, centered and readable, with enough contrast.
- Clean sticker composition, simple or transparent-looking background, no watermark, no logo, no photorealistic human, no busy scenery.
- Do not redesign the character.
- The whole character and text should fit comfortably inside the canvas.
""".strip()


def process_for_line(raw_bytes):
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
    max_w, max_h = 370, 320
    scale = min(max_w / img.width, max_h / img.height, 1.0)
    new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    img = img.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGBA", (max_w, max_h), (255, 255, 255, 0))
    x = (max_w - img.width) // 2
    y = (max_h - img.height) // 2
    canvas.alpha_composite(img, (x, y))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def qa_image(png_bytes):
    img = Image.open(io.BytesIO(png_bytes))
    checks = {
        "PNG": img.format == "PNG",
        "尺寸": img.size == (370, 320),
        "RGBA": img.mode == "RGBA",
        "檔案大小 < 1 MB": len(png_bytes) < 1024 * 1024,
    }
    return checks


def zip_outputs(items):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for idx, data in items:
            z.writestr(f"sticker_{idx:02d}.png", data)
        manifest = {
            "app": "LINE Sticker Factory v0.6",
            "count": len(items),
            "files": [f"sticker_{idx:02d}.png" for idx, _ in items],
        }
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return out.getvalue()


st.set_page_config(page_title=APP_TITLE, page_icon="🎨", layout="centered")
st.title(APP_TITLE)
st.caption("一句話 → 選情境 → AI 寫腳本 → 固定使用你的主角 → 生成貼圖 → 預覽與下載")

if "scripts" not in st.session_state:
    st.session_state.scripts = []
if "generated" not in st.session_state:
    st.session_state.generated = []
if "character_bytes" not in st.session_state:
    st.session_state.character_bytes = None

with st.expander("ℹ️ 這一版的核心流程", expanded=True):
    st.write("你不需要自己一張一張想台詞。先告訴 AI「想表達什麼」，再選一個情境，AI 會自動規劃一整套貼圖腳本。")

st.subheader("① 上傳主角")
uploaded = st.file_uploader("上傳你的主角參考圖", type=["png", "jpg", "jpeg"])
if uploaded:
    st.session_state.character_bytes = uploaded.getvalue()
if st.session_state.character_bytes:
    st.image(st.session_state.character_bytes, caption="目前固定使用的主角", width=180)

character_note = st.text_area(
    "角色設定（可選）",
    value="可愛 Q 版女孩；以我上傳的參考圖為最高優先，保持髮型、圓框眼鏡、臉型、眼睛、服裝與整體比例一致。",
    height=90,
)

st.subheader("② 選擇情境")
scenario = st.selectbox("這一套貼圖主要用在哪裡？", list(SCENARIOS.keys()))
scenario_desc = SCENARIOS[scenario]
if scenario == "自訂情境":
    scenario_desc = st.text_area("請描述你的情境", placeholder="例如：家人群組、寵物主人日常、客服回覆……")

st.subheader("③ 告訴 AI 你想表達什麼")
idea = st.text_area(
    "用一句話描述",
    placeholder="例如：最近工作好多，每天都好累，但又要假裝自己沒事",
    height=100,
)

st.subheader("④ 貼圖數量")
count = st.radio("數量", [8, 16, 24], horizontal=True, index=0)

if st.button("✨ 自動寫劇本", type="primary", use_container_width=True):
    if not st.session_state.character_bytes:
        st.error("請先上傳主角參考圖。")
    elif not idea.strip():
        st.error("請先輸入一句話。")
    else:
        with st.spinner("AI 正在依照情境規劃整套腳本……"):
            try:
                st.session_state.scripts = call_text_ai(
                    build_script_prompt(scenario, scenario_desc, idea, count, character_note)
                )
                st.session_state.generated = []
                st.success(f"已產生 {len(st.session_state.scripts)} 格腳本。你可以先修改台詞，再生成圖片。")
            except Exception as e:
                st.error(str(e))

if st.session_state.scripts:
    st.subheader("⑤ AI 劇本（可直接修改）")
    st.caption("先把台詞改成你真正想用的版本，再按下面的按鈕生成圖片。")

    edited = []
    for i, s in enumerate(st.session_state.scripts):
        with st.container(border=True):
            st.markdown(f"**第 {i+1} 格**")
            text = st.text_input("台詞", s["text"], key=f"text_{i}")
            c1, c2 = st.columns(2)
            with c1:
                action = st.text_input("動作", s["action"], key=f"action_{i}")
            with c2:
                expression = st.text_input("表情", s["expression"], key=f"expr_{i}")
            scene = st.text_input("簡單背景", s["scene"], key=f"scene_{i}")
            edited.append({
                "index": i + 1,
                "text": text,
                "action": action,
                "expression": expression,
                "scene": scene,
            })
    st.session_state.scripts = edited

    if st.button("🎨 開始製作貼圖", type="primary", use_container_width=True):
        st.session_state.generated = []
        total = len(st.session_state.scripts)
        progress = st.progress(0)
        for i, script in enumerate(st.session_state.scripts):
            try:
                prompt = make_image_prompt(script, scenario, character_note)
                raw = image_edit(st.session_state.character_bytes, prompt)
                processed = process_for_line(raw)
                qa = qa_image(processed)
                st.session_state.generated.append({
                    "index": i + 1,
                    "text": script["text"],
                    "data": processed,
                    "qa": qa,
                })
                progress.progress((i + 1) / total)
            except Exception as e:
                st.session_state.generated.append({
                    "index": i + 1,
                    "text": script["text"],
                    "data": None,
                    "qa": {"錯誤": str(e)},
                })
                progress.progress((i + 1) / total)

if st.session_state.generated:
    st.subheader("⑥ 預覽與 QA")
    good_items = []
    for item in st.session_state.generated:
        with st.container(border=True):
            st.markdown(f"**{item['index']:02d}｜{item['text']}**")
            if item["data"]:
                st.image(item["data"], width=260)
                qa = item["qa"]
                st.write("、".join([f"{k}: {'✅' if v else '❌'}" for k, v in qa.items()]))
                if all(qa.values()):
                    good_items.append((item["index"], item["data"]))
            else:
                st.error(item["qa"].get("錯誤", "未知錯誤"))

    if good_items:
        zip_bytes = zip_outputs(good_items)
        st.download_button(
            "📦 下載 LINE 貼圖 ZIP",
            data=zip_bytes,
            file_name="line-stickers-v0.6.zip",
            mime="application/zip",
            use_container_width=True,
        )

st.divider()
st.caption("本版本使用 Pollinations API。API 生成需要 API key，圖片/文字生成會消耗 Pollen；免費 Quest Pollen 是否可用取決於你的帳戶與當時活動。")
