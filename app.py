import os, io, json, base64, zipfile
from pathlib import Path
import requests
import streamlit as st
from PIL import Image, ImageDraw

st.set_page_config(page_title="LINE Sticker Factory", page_icon="🎨", layout="centered")

st.markdown("""
<style>
.block-container {max-width:760px;padding:1rem 1rem 3rem}
.stButton>button,.stDownloadButton>button{width:100%;min-height:50px;border-radius:14px;font-size:1.05rem}
.stTextArea textarea,.stTextInput input{font-size:16px}
</style>
""", unsafe_allow_html=True)

BASE = Path(".")
WORK = BASE / "sticker_projects"
ASSETS = WORK / "assets"
WORK.mkdir(exist_ok=True)
ASSETS.mkdir(exist_ok=True)

POLLINATIONS_URL = "https://gen.pollinations.ai/v1/images/edits"


def get_secret(name):
    try:
        value = st.secrets.get(name)
        if value:
            return value
    except Exception:
        pass
    return os.getenv(name)


def sticker_plan(quantity):
    base = [
        ("早安", "sleepy_happy", "wave"),
        ("收到", "calm", "salute"),
        ("好累", "exhausted", "slump"),
        ("辛苦了", "warm", "thumbs_up"),
        ("傻眼", "speechless", "blank_stare"),
        ("不想上班", "despair", "hide_under_blanket"),
        ("下班啦", "excited", "run_out"),
        ("晚安", "sleepy", "sleep"),
    ]
    return [
        {"id": f"{i+1:03d}", "text": base[i % 8][0],
         "emotion": base[i % 8][1], "action": base[i % 8][2]}
        for i in range(quantity)
    ]


def character_bible():
    return {
        "name": "主角",
        "reference": "user_uploaded_reference",
        "visual_identity": "沿用使用者上傳的主角圖片，不重新設計角色",
        "rules": [
            "保持原始髮型、圓框眼鏡、臉型、身形、服裝識別特徵",
            "保持可愛、圓潤、chibi 角色比例",
            "每張貼圖只出現主角",
            "不要擅自更換角色外觀"
        ]
    }


def make_prompt(c, s, idea):
    return f"""Create one polished LINE sticker using the supplied character reference image as the SAME main character.

USER THEME:
{idea}

CHARACTER IDENTITY — IMPORTANT:
Preserve the recognizable hairstyle, round glasses, face proportions, body proportions, clothing identity and cute chibi appearance from the reference image. Do not redesign the character. Keep the character visually consistent with the reference.

STICKER:
Traditional Chinese text: 「{s['text']}」
Emotion: {s['emotion']}
Action: {s['action']}

COMPOSITION:
One character only, expressive pose, clear silhouette, centered sticker composition, clean polished LINE-sticker illustration, large readable Traditional Chinese text, transparent or clean plain background.

DO NOT:
change hairstyle, remove glasses, change outfit identity, add another person, add watermark, add logo, create a photorealistic human, or create a busy background.
"""


def generate_pollinations(prompt, reference_path, output):
    key = get_secret("POLLINATIONS_API_KEY")
    if not key:
        raise RuntimeError("尚未設定 POLLINATIONS_API_KEY")

    # Pollinations supports OpenAI-compatible multipart image editing.
    # 'kontext' is used because it is intended for reference-image editing.
    with open(reference_path, "rb") as f:
        files = {"image": (reference_path.name, f, "image/png")}
        data = {
            "prompt": prompt,
            "model": os.getenv("POLLINATIONS_IMAGE_MODEL", "kontext"),
            "size": "1024x1024",
        }
        headers = {"Authorization": f"Bearer {key}"}
        response = requests.post(
            POLLINATIONS_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=180,
        )

    if response.status_code >= 400:
        detail = response.text[:1200]
        raise RuntimeError(f"Pollinations API 錯誤 {response.status_code}: {detail}")

    try:
        payload = response.json()
    except Exception:
        raise RuntimeError("Pollinations API 回傳的不是 JSON")

    item = (payload.get("data") or [{}])[0]
    b64 = item.get("b64_json")
    url = item.get("url")

    if b64:
        output.write_bytes(base64.b64decode(b64))
        return

    if url:
        img_response = requests.get(url, timeout=180)
        img_response.raise_for_status()
        output.write_bytes(img_response.content)
        return

    raise RuntimeError("Pollinations 沒有回傳圖片資料")


def process_image(src, dst):
    img = Image.open(src).convert("RGBA")
    alpha = img.getchannel("A")
    bbox = alpha.getbbox()
    if bbox:
        img = img.crop(bbox)
    img.thumbnail((322, 272), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (370, 320), (255, 255, 255, 0))
    canvas.alpha_composite(img, ((370-img.width)//2, (320-img.height)//2))
    canvas.save(dst, "PNG", optimize=True)


def make_preview(files, output):
    cols, cell_w, cell_h = 4, 370, 350
    rows = (len(files)+cols-1)//cols
    canvas = Image.new("RGB", (cols*cell_w, rows*cell_h), "white")
    draw = ImageDraw.Draw(canvas)
    for i, f in enumerate(files):
        img = Image.open(f).convert("RGBA")
        bg = Image.new("RGBA", img.size, "white")
        bg.alpha_composite(img)
        img = bg.convert("RGB")
        img.thumbnail((370, 320))
        x = (i % cols) * cell_w
        y = (i // cols) * cell_h
        canvas.paste(img, (x, y))
        draw.text((x+8, y+325), f.stem, fill="black")
    canvas.save(output, "PNG")


st.title("🎨 LINE Sticker Factory")
st.caption("手機版 · 免費額度版 · 一句話 → AI 貼圖")

st.info("本版本改用 Pollinations 圖片 API，不再使用 OpenAI API。免費額度仍受服務商的 Pollen / 使用限制影響，並非保證無限免費。")

st.subheader("① 上傳主角")
uploaded = st.file_uploader("主角參考圖片", type=["png", "jpg", "jpeg", "webp"])
if uploaded:
    ref = ASSETS / "reference_character.png"
    ref.write_bytes(uploaded.getbuffer())
    st.image(uploaded, caption="目前主角參考圖", use_container_width=True)
else:
    ref = ASSETS / "reference_character.png"
    if ref.exists():
        st.image(str(ref), caption="目前主角參考圖", use_container_width=True)

st.subheader("② 貼圖需求")
idea = st.text_area("一句話描述", "可愛厭世上班族角色", height=90)
quantity = st.selectbox("張數", [8, 16, 24, 40], index=0)

if st.button("🚀 開始製作", type="primary"):
    if not ref.exists():
        st.error("請先上傳主角圖片。")
        st.stop()

    if not get_secret("POLLINATIONS_API_KEY"):
        st.error("請先在 Streamlit Secrets 設定 POLLINATIONS_API_KEY。")
        st.stop()

    project = WORK / "current"
    generated = project / "generated"
    processed = project / "processed"
    delivery = project / "delivery"
    for d in [generated, processed, delivery]:
        d.mkdir(parents=True, exist_ok=True)

    bible = character_bible()
    stickers = sticker_plan(quantity)
    prompts = [dict(s, prompt=make_prompt(bible, s, idea)) for s in stickers]

    (project/"project.json").write_text(json.dumps({
        "theme": idea, "quantity": quantity, "language": "zh-TW",
        "generator": "pollinations", "model": os.getenv("POLLINATIONS_IMAGE_MODEL", "kontext")
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (project/"character.json").write_text(json.dumps(bible, ensure_ascii=False, indent=2), encoding="utf-8")
    (project/"sticker_list.json").write_text(json.dumps(stickers, ensure_ascii=False, indent=2), encoding="utf-8")
    (project/"prompts.json").write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        with st.status("正在製作…", expanded=True) as status:
            progress = st.progress(0)
            for i, item in enumerate(prompts):
                out = generated / f"{item['id']}.png"
                if not out.exists():
                    st.write(f"🎨 生成 {item['id']}｜{item['text']}")
                    generate_pollinations(item["prompt"], ref, out)
                progress.progress((i+1)/len(prompts))

            st.write("✂️ 圖片處理")
            for f in sorted(generated.glob("*.png")):
                process_image(f, processed/f.name)

            st.write("🔍 QA")
            files = sorted(processed.glob("*.png"))
            issues = []
            for f in files:
                try:
                    with Image.open(f) as im:
                        if im.mode != "RGBA": issues.append(f"{f.name}: mode")
                        if im.size != (370, 320): issues.append(f"{f.name}: size")
                except Exception:
                    issues.append(f"{f.name}: corrupt")
                if f.stat().st_size > 1_000_000:
                    issues.append(f"{f.name}: too large")
            if len(files) != quantity:
                issues.append("sticker count mismatch")
            if issues:
                status.update(label="QA 未通過", state="error")
                st.error("有問題：" + ", ".join(issues))
                st.stop()

            st.write("📦 打包")
            preview = delivery / "preview.png"
            make_preview(files, preview)
            for f in files:
                target = delivery / f"sticker_{f.stem}.png"
                target.write_bytes(f.read_bytes())

            metadata = {
                "theme": idea,
                "quantity": quantity,
                "status": "PASS",
                "generator": "pollinations",
                "model": os.getenv("POLLINATIONS_IMAGE_MODEL", "kontext")
            }
            (delivery/"metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

            package = delivery / "LINE_Sticker_Package.zip"
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as z:
                for f in delivery.iterdir():
                    if f.is_file() and f != package:
                        z.write(f, f.name)
            status.update(label="完成！", state="complete")

        st.success(f"🎉 {quantity} 張貼圖完成")
        st.image(str(preview), caption="整套預覽", use_container_width=True)
        st.download_button(
            "📦 下載完整素材包", package.read_bytes(),
            file_name="LINE_Sticker_Package.zip", mime="application/zip"
        )
    except Exception as e:
        st.error("製作失敗。請確認 Pollinations API Key 與免費額度是否可用。")
        st.exception(e)

st.divider()
st.caption("LINE Sticker Factory Mobile v0.5 · Pollinations edition")
