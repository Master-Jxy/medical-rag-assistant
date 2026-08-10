"""Rebuild the privacy-free Stage 26.2b vision/OCR PNG fixture set."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "assets"
SIZE = (640, 400)
random.seed(2602)

FONT = ImageFont.load_default(size=22)
SMALL_FONT = ImageFont.load_default(size=16)

# Simple stroke glyphs keep the synthetic Chinese labels independent of OS fonts.
CJK_STROKES = {
    "合": [((1, 5), (6, 1)), ((6, 1), (11, 5)), ((3, 5), (9, 5)), ((3, 7), (9, 7)), ((3, 7), (3, 11)), ((3, 11), (9, 11)), ((9, 7), (9, 11))],
    "成": [((2, 3), (10, 3)), ((3, 3), (2, 11)), ((2, 8), (6, 8)), ((6, 1), (8, 11)), ((11, 4), (7, 10)), ((7, 10), (11, 11))],
    "中": [((2, 3), (10, 3)), ((2, 3), (2, 9)), ((2, 9), (10, 9)), ((10, 3), (10, 9)), ((6, 1), (6, 11))],
    "文": [((6, 1), (6, 2)), ((2, 3), (10, 3)), ((4, 4), (8, 9)), ((8, 4), (3, 11)), ((3, 6), (10, 11))],
    "界": [((2, 1), (10, 1)), ((2, 1), (2, 7)), ((10, 1), (10, 7)), ((2, 7), (10, 7)), ((6, 1), (6, 7)), ((2, 4), (10, 4)), ((4, 8), (3, 11)), ((8, 8), (9, 11))],
    "面": [((2, 1), (10, 1)), ((3, 3), (9, 3)), ((3, 3), (3, 9)), ((9, 3), (9, 9)), ((3, 6), (9, 6)), ((2, 1), (2, 11)), ((2, 11), (10, 11)), ((10, 1), (10, 11))],
    "体": [((3, 1), (1, 6)), ((2, 5), (2, 11)), ((7, 1), (7, 11)), ((4, 4), (10, 4)), ((7, 4), (4, 9)), ((7, 4), (10, 9))],
    "温": [((1, 3), (2, 4)), ((1, 6), (2, 6)), ((2, 8), (1, 11)), ((4, 1), (10, 1)), ((4, 1), (4, 6)), ((4, 6), (10, 6)), ((10, 1), (10, 6)), ((4, 3), (10, 3)), ((3, 8), (11, 8)), ((3, 8), (3, 11)), ((11, 8), (11, 11)), ((3, 11), (11, 11)), ((6, 8), (6, 11)), ((8, 8), (8, 11))],
    "正": [((3, 2), (10, 2)), ((6, 2), (6, 10)), ((2, 10), (11, 10)), ((3, 6), (3, 10)), ((3, 7), (6, 7))],
    "常": [((3, 1), (4, 3)), ((6, 1), (6, 3)), ((9, 1), (8, 3)), ((2, 4), (10, 4)), ((2, 4), (2, 6)), ((10, 4), (10, 6)), ((3, 7), (9, 7)), ((3, 7), (3, 10)), ((9, 7), (9, 10)), ((6, 6), (6, 11))],
    "说": [((1, 2), (3, 3)), ((2, 5), (3, 6)), ((3, 6), (2, 11)), ((5, 2), (7, 4)), ((10, 2), (8, 4)), ((5, 5), (10, 5)), ((5, 5), (5, 8)), ((5, 8), (10, 8)), ((10, 5), (10, 8)), ((7, 8), (5, 11)), ((8, 8), (10, 11))],
    "明": [((1, 2), (5, 2)), ((1, 2), (1, 10)), ((1, 10), (5, 10)), ((5, 2), (5, 10)), ((1, 6), (5, 6)), ((7, 1), (11, 1)), ((7, 1), (7, 11)), ((11, 1), (11, 11)), ((7, 5), (11, 5)), ((7, 8), (11, 8))],
    "报": [((1, 3), (5, 3)), ((3, 1), (3, 11)), ((1, 7), (5, 6)), ((6, 2), (10, 2)), ((6, 2), (6, 11)), ((6, 5), (10, 5)), ((10, 2), (10, 5)), ((7, 7), (10, 11)), ((10, 7), (7, 11))],
    "告": [((4, 1), (4, 5)), ((2, 3), (10, 3)), ((1, 5), (11, 5)), ((3, 7), (9, 7)), ((3, 7), (3, 11)), ((3, 11), (9, 11)), ((9, 7), (9, 11))],
}


def draw_cjk(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, scale: int = 3, color=(20, 45, 55)) -> None:
    x, y = xy
    for char in text:
        for start, end in CJK_STROKES[char]:
            draw.line(
                (x + start[0] * scale, y + start[1] * scale, x + end[0] * scale, y + end[1] * scale),
                fill=color,
                width=max(2, scale),
            )
        x += 14 * scale


def canvas(color=(247, 249, 248)) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", SIZE, color)
    return image, ImageDraw.Draw(image)


def save(image: Image.Image, name: str) -> None:
    image.save(ASSET_DIR / name, format="PNG", optimize=False, compress_level=9)


def build_images() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    image, draw = canvas((226, 231, 225))
    draw.rectangle((60, 55, 580, 350), fill=(181, 155, 119))
    draw.rectangle((105, 95, 390, 310), fill=(246, 244, 235), outline=(50, 75, 80), width=4)
    draw.text((145, 135), "SYNTHETIC NOTE", font=FONT, fill=(18, 55, 64))
    draw.text((145, 180), "DEMO ONLY", font=FONT, fill=(25, 105, 120))
    draw.ellipse((430, 120, 535, 225), fill=(231, 238, 235), outline=(55, 95, 90), width=4)
    draw.arc((515, 145, 575, 210), 250, 110, fill=(55, 95, 90), width=5)
    save(image, "01_ordinary_complete.png")

    image, draw = canvas()
    draw.rectangle((42, 35, 598, 365), fill=(255, 255, 255), outline=(45, 75, 86), width=4)
    draw.rectangle((42, 35, 598, 82), fill=(32, 93, 101))
    draw_cjk(draw, (75, 108), "合成中文界面", scale=3)
    draw.line((75, 166, 560, 166), fill=(201, 211, 210), width=2)
    draw_cjk(draw, (80, 198), "体温", scale=3)
    draw.text((275, 205), "36.8 C", font=FONT, fill=(20, 45, 55))
    draw_cjk(draw, (435, 198), "正常", scale=3, color=(25, 125, 80))
    draw.text((80, 290), "SYNTHETIC DEMO", font=SMALL_FONT, fill=(95, 110, 112))
    save(image, "02_chinese_screenshot.png")

    image, draw = canvas((250, 252, 255))
    draw.rectangle((55, 55, 585, 345), fill=(255, 255, 255), outline=(69, 88, 118), width=3)
    draw_cjk(draw, (85, 95), "说明", scale=4)
    draw.text((225, 105), "ENGLISH DEMO", font=FONT, fill=(35, 59, 91))
    draw.text((85, 205), "TEMP 36.8 C", font=FONT, fill=(15, 83, 92))
    draw.text((85, 260), "STATUS NORMAL", font=FONT, fill=(20, 120, 72))
    save(image, "03_mixed_text.png")

    image, draw = canvas()
    x0, y0, x1, y1 = 45, 55, 595, 345
    draw.rectangle((x0, y0, x1, y1), fill="white", outline=(42, 67, 77), width=3)
    for x in (45, 280, 435, 595):
        draw.line((x, y0, x, y1), fill=(42, 67, 77), width=2)
    for y in (55, 125, 195, 265, 345):
        draw.line((x0, y, x1, y), fill=(42, 67, 77), width=2)
    rows = [("ITEM", "VALUE", "UNIT"), ("TEMP", "36.8", "C"), ("PULSE", "72", "BPM"), ("DEMO", "ONLY", "-")]
    for row_index, row in enumerate(rows):
        y = 78 + row_index * 70
        for x, value in zip((70, 305, 460), row):
            draw.text((x, y), value, font=SMALL_FONT, fill=(25, 50, 60))
    save(image, "04_table.png")

    image, draw = canvas((246, 247, 243))
    draw.rectangle((65, 30, 575, 370), fill="white", outline=(42, 61, 65), width=3)
    draw.rectangle((65, 30, 575, 78), fill=(225, 236, 233))
    draw.text((105, 44), "SYNTHETIC DEMO REPORT", font=FONT, fill=(19, 64, 70))
    draw.text((105, 110), "NO PERSON / NO RECORD", font=SMALL_FONT, fill=(130, 40, 45))
    draw.line((105, 155, 535, 155), fill=(180, 190, 190), width=2)
    draw.text((105, 185), "GLUCOSE", font=FONT, fill=(30, 48, 55))
    draw.text((340, 185), "5.2 mmol/L", font=FONT, fill=(30, 48, 55))
    draw.text((105, 250), "REFERENCE", font=SMALL_FONT, fill=(70, 80, 82))
    draw.text((340, 250), "3.9 - 6.1", font=SMALL_FONT, fill=(70, 80, 82))
    draw.text((105, 315), "FAKE DATA", font=SMALL_FONT, fill=(25, 110, 95))
    save(image, "05_demo_report.png")

    image, draw = canvas()
    draw.text((95, 150), "BLURRED SYNTHETIC TEXT 36.8", font=FONT, fill=(25, 45, 55))
    image = image.filter(ImageFilter.GaussianBlur(radius=7))
    save(image, "06_blurred.png")

    image, draw = canvas()
    draw.rectangle((0, 75, 690, 320), fill="white", outline=(50, 70, 75), width=3)
    draw.text((-92, 125), "CROPPED LEFT CONTENT", font=FONT, fill=(30, 52, 58))
    draw.text((455, 235), "RIGHT CONTENT CUT", font=FONT, fill=(30, 52, 58))
    draw.rectangle((600, 0, 639, 399), fill=(247, 249, 248))
    save(image, "07_cropped.png")

    image, draw = canvas((255, 255, 255))
    draw.rectangle((1, 1, 638, 398), outline=(245, 245, 245), width=2)
    save(image, "08_blank.png")


def fixture_entries() -> list[dict]:
    return [
        {
            "filename": "01_ordinary_complete.png",
            "case_id": "ordinary_complete",
            "expected_route": "overview_only",
            "expected_text_tokens": ["SYNTHETIC NOTE", "DEMO ONLY"],
            "expected_measurements": [],
            "expected_table_rows": [],
            "overview": {"image_type": "photo", "summary": "A complete synthetic desk scene", "visible_text": ["SYNTHETIC NOTE", "DEMO ONLY"], "objects": ["note", "cup"], "spatial_notes": ["note left of cup"]},
            "extraction": {},
            "fake_usage": {"input_tokens": 0, "output_tokens": 0},
        },
        {
            "filename": "02_chinese_screenshot.png",
            "case_id": "chinese_screenshot",
            "expected_route": "ocr_mode",
            "expected_text_tokens": ["合成中文界面", "体温", "36.8 C", "正常"],
            "expected_measurements": [{"name": "体温", "value": "36.8", "unit": "C"}],
            "expected_table_rows": [],
            "overview": {"image_type": "document", "summary": "A synthetic Chinese interface screenshot", "visible_text": ["合成中文界面"], "uncertain_content": ["remaining small text is unclear"]},
            "extraction": {"visible_text": ["合成中文界面", "体温", "36.8 C", "正常"], "measurements": [{"name": "体温", "value": "36.8", "unit": "C"}]},
            "fake_usage": {"input_tokens": 80, "output_tokens": 24},
        },
        {
            "filename": "03_mixed_text.png",
            "case_id": "mixed_text",
            "expected_route": "ocr_mode",
            "expected_text_tokens": ["说明", "ENGLISH DEMO", "TEMP 36.8 C", "STATUS NORMAL"],
            "expected_measurements": [{"name": "TEMP", "value": "36.8", "unit": "C"}],
            "expected_table_rows": [],
            "overview": {"image_type": "document", "summary": "A mixed Chinese and English synthetic card", "visible_text": ["ENGLISH DEMO"], "uncertain_content": ["Chinese heading needs exact extraction"]},
            "extraction": {"visible_text": ["说明", "ENGLISH DEMO", "TEMP 36.8 C", "STATUS NORMAL"], "measurements": [{"name": "TEMP", "value": "36.8", "unit": "C"}]},
            "fake_usage": {"input_tokens": 84, "output_tokens": 28},
        },
        {
            "filename": "04_table.png",
            "case_id": "table",
            "expected_route": "ocr_mode",
            "expected_text_tokens": ["ITEM", "VALUE", "UNIT", "TEMP", "PULSE"],
            "expected_measurements": [{"name": "TEMP", "value": "36.8", "unit": "C"}, {"name": "PULSE", "value": "72", "unit": "BPM"}],
            "expected_table_rows": [["ITEM", "VALUE", "UNIT"], ["TEMP", "36.8", "C"], ["PULSE", "72", "BPM"]],
            "overview": {"image_type": "medical_report", "summary": "A synthetic table with measurements", "visible_text": ["ITEM VALUE UNIT"], "uncertain_content": ["table cells need exact extraction"]},
            "extraction": {"visible_text": ["ITEM", "VALUE", "UNIT", "TEMP", "PULSE"], "measurements": [{"name": "TEMP", "value": "36.8", "unit": "C"}, {"name": "PULSE", "value": "72", "unit": "BPM"}], "table_rows": [["ITEM", "VALUE", "UNIT"], ["TEMP", "36.8", "C"], ["PULSE", "72", "BPM"]]},
            "fake_usage": {"input_tokens": 92, "output_tokens": 42},
        },
        {
            "filename": "05_demo_report.png",
            "case_id": "demo_report",
            "expected_route": "ocr_mode",
            "expected_text_tokens": ["SYNTHETIC DEMO REPORT", "NO PERSON / NO RECORD", "GLUCOSE", "5.2 mmol/L", "FAKE DATA"],
            "expected_measurements": [{"name": "GLUCOSE", "value": "5.2", "unit": "mmol/L"}],
            "expected_table_rows": [],
            "overview": {"image_type": "medical_report", "summary": "A clearly synthetic report", "visible_text": []},
            "extraction": {"visible_text": ["SYNTHETIC DEMO REPORT", "NO PERSON / NO RECORD", "GLUCOSE", "5.2 mmol/L", "FAKE DATA"], "measurements": [{"name": "GLUCOSE", "value": "5.2", "unit": "mmol/L", "reference_range": "3.9 - 6.1", "flag": "normal"}]},
            "fake_usage": {"input_tokens": 96, "output_tokens": 44},
        },
        {
            "filename": "06_blurred.png",
            "case_id": "blurred",
            "expected_route": "reupload_required",
            "expected_text_tokens": [],
            "expected_measurements": [],
            "expected_table_rows": [],
            "overview": {"image_type": "document", "summary": "The synthetic text cannot be read reliably", "uncertain_content": ["image is blurry"]},
            "extraction": {},
            "fake_usage": {"input_tokens": 0, "output_tokens": 0},
        },
        {
            "filename": "07_cropped.png",
            "case_id": "cropped",
            "expected_route": "reupload_required",
            "expected_text_tokens": [],
            "expected_measurements": [],
            "expected_table_rows": [],
            "overview": {"image_type": "document", "summary": "The synthetic document is incomplete", "visible_text": ["CONTENT"], "uncertain_content": ["left and right edges are cropped"]},
            "extraction": {},
            "fake_usage": {"input_tokens": 0, "output_tokens": 0},
        },
        {
            "filename": "08_blank.png",
            "case_id": "blank",
            "expected_route": "reupload_required",
            "expected_text_tokens": [],
            "expected_measurements": [],
            "expected_table_rows": [],
            "overview": {"image_type": "blank", "summary": "A blank synthetic image with no visible content"},
            "extraction": {},
            "fake_usage": {"input_tokens": 0, "output_tokens": 0},
        },
    ]


def write_manifest() -> None:
    assets = []
    for entry in fixture_entries():
        path = ASSET_DIR / entry["filename"]
        with Image.open(path) as image:
            dimensions = list(image.size)
        assets.append(
            {
                **entry,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "dimensions": dimensions,
                "privacy": "synthetic",
            }
        )
    manifest = {
        "schema_version": "vision-ocr-v1",
        "generated_by": "build_assets.py",
        "automatic_retries": 0,
        "assets": assets,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    build_images()
    write_manifest()
    print(f"generated {len(fixture_entries())} synthetic PNG fixtures")


if __name__ == "__main__":
    main()
