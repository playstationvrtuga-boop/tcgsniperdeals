from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

try:
    from vip_app.app.extensions import db
    from vip_app.app.models import CardmarketTrend, utcnow
except ImportError:  # Render rootDir=vip_app can import the Flask package as "app".
    from app.extensions import db
    from app.models import CardmarketTrend, utcnow


ALLOWED_SCREENSHOT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class ScreenshotTrendSlot:
    category: str
    rank: int
    image_url: str
    product_name: str
    price: float | None = None
    currency: str = "EUR"
    expansion: str | None = None
    card_number: str | None = None


def _static_url(relative_path: Path) -> str:
    return "/static/" + relative_path.as_posix().lstrip("/")


def _extract_price(text: str) -> float | None:
    match = re.search(r"(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:EUR|€)", text, re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _split_cardmarket_name(value: str) -> tuple[str, str | None, str | None]:
    clean = re.sub(r"\s+", " ", value).strip(" -|")
    match = re.search(r"\(([^()]+)\)\s*$", clean)
    if not match:
        return clean, None, None
    meta = match.group(1).strip()
    name = clean[: match.start()].strip()
    parts = meta.split()
    if len(parts) >= 2:
        return name, " ".join(parts[:-1]), parts[-1]
    return name, meta, None


def parse_cardmarket_screenshot_text(text: str, max_items: int = 3) -> list[ScreenshotTrendSlot]:
    """Best-effort parser for OCR/pasted Cardmarket trend text."""
    slots: list[ScreenshotTrendSlot] = []
    category: str | None = None
    rank_by_category = {"best_sellers": 0, "best_bargains": 0}
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    for line in lines:
        lowered = line.lower()
        if "best sellers" in lowered:
            category = "best_sellers"
            continue
        if "best bargains" in lowered:
            category = "best_bargains"
            continue
        if not category or rank_by_category[category] >= max_items:
            continue
        if "€" not in line and "eur" not in lowered:
            continue
        price = _extract_price(line)
        name_part = re.sub(r"\d{1,5}(?:[.,]\d{1,2})?\s*(?:EUR|€).*", "", line, flags=re.IGNORECASE).strip(" -|")
        name_part = re.sub(r"^\d+[\).:\-\s]+", "", name_part).strip()
        if not name_part:
            continue
        name, expansion, card_number = _split_cardmarket_name(name_part)
        rank_by_category[category] += 1
        slots.append(
            ScreenshotTrendSlot(
                category=category,
                rank=rank_by_category[category],
                image_url="",
                product_name=name,
                expansion=expansion,
                card_number=card_number,
                price=price,
            )
        )
    return slots


def _ocr_text_if_available(image_path: Path) -> str:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return ""
    try:
        return pytesseract.image_to_string(Image.open(image_path))
    except Exception as error:
        print(f"[ai_market_intel] screenshot OCR unavailable error={error}", flush=True)
        return ""


def _file_present(file: FileStorage | None) -> bool:
    return bool(file and file.filename)


def _save_upload(file: FileStorage, original_dir: Path, prefix: str) -> Path:
    filename = secure_filename(file.filename or f"{prefix}.png")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_SCREENSHOT_EXTENSIONS:
        raise ValueError("Use PNG, JPG, JPEG or WEBP screenshots.")
    original_dir.mkdir(parents=True, exist_ok=True)
    output_path = original_dir / f"{prefix}_{filename}"
    file.save(output_path)
    return output_path


def _category_grid_boxes(category: str) -> list[tuple[str, int, tuple[float, float, float, float]]]:
    # Ratios tuned for mobile/vertical Cardmarket grid screenshots.
    x_ranges = [(0.140, 0.370), (0.390, 0.620), (0.640, 0.870)]
    y_ranges = [(0.055, 0.285), (0.300, 0.530), (0.545, 0.775)]
    boxes: list[tuple[str, int, tuple[float, float, float, float]]] = []
    rank = 1
    for top, bottom in y_ranges:
        for left, right in x_ranges:
            boxes.append((category, rank, (left, top, right, bottom)))
            rank += 1
    return boxes


def _crop_trend_images(
    image_path: Path,
    output_dir: Path,
    static_root: Path,
    *,
    category: str | None = None,
) -> list[tuple[str, int, str]]:
    try:
        from PIL import Image  # type: ignore
    except Exception as error:
        raise RuntimeError("Pillow is required for screenshot image extraction") from error

    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    output_dir.mkdir(parents=True, exist_ok=True)

    if category:
        boxes = _category_grid_boxes(category)
    else:
        # Ratios tuned for the public Cardmarket Pokemon trends page desktop layout.
        boxes = [
            ("best_sellers", 1, (0.170, 0.300, 0.290, 0.585)),
            ("best_sellers", 2, (0.295, 0.300, 0.415, 0.585)),
            ("best_sellers", 3, (0.425, 0.300, 0.535, 0.585)),
            ("best_bargains", 1, (0.550, 0.300, 0.670, 0.585)),
            ("best_bargains", 2, (0.675, 0.300, 0.795, 0.585)),
            ("best_bargains", 3, (0.800, 0.300, 0.920, 0.585)),
        ]
    crops: list[tuple[str, int, str]] = []
    for category, rank, ratios in boxes:
        left, top, right, bottom = ratios
        crop = image.crop((int(width * left), int(height * top), int(width * right), int(height * bottom)))
        filename = f"{image_path.stem}_{category}_{rank}.jpg"
        crop_path = output_dir / filename
        crop.save(crop_path, format="JPEG", quality=86, optimize=True)
        crops.append((category, rank, _static_url(crop_path.relative_to(static_root))))
    return crops


def import_cardmarket_trends_from_screenshots(
    *,
    combined_screenshot: FileStorage | None = None,
    sellers_screenshot: FileStorage | None = None,
    bargains_screenshot: FileStorage | None = None,
    pasted_text: str = "",
    source_url: str = "https://www.cardmarket.com/en/Pokemon",
) -> int:
    static_root = Path(__file__).resolve().parent.parent / "vip_app" / "app" / "static"
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    import_dir = static_root / "uploads" / "market_intel" / stamp
    original_dir = import_dir / "original"
    crop_dir = import_dir / "cards"

    crops: list[tuple[str, int, str]] = []
    original_urls: list[str] = []
    ocr_chunks: list[str] = []

    if _file_present(combined_screenshot):
        original_path = _save_upload(combined_screenshot, original_dir, "combined")
        original_urls.append(_static_url(original_path.relative_to(static_root)))
        crops.extend(_crop_trend_images(original_path, crop_dir, static_root))
        ocr_chunks.append(_ocr_text_if_available(original_path))

    if _file_present(sellers_screenshot):
        original_path = _save_upload(sellers_screenshot, original_dir, "best_sellers")
        original_urls.append(_static_url(original_path.relative_to(static_root)))
        crops.extend(_crop_trend_images(original_path, crop_dir, static_root, category="best_sellers"))
        ocr_chunks.append("Best Sellers\n" + _ocr_text_if_available(original_path))

    if _file_present(bargains_screenshot):
        original_path = _save_upload(bargains_screenshot, original_dir, "best_bargains")
        original_urls.append(_static_url(original_path.relative_to(static_root)))
        crops.extend(_crop_trend_images(original_path, crop_dir, static_root, category="best_bargains"))
        ocr_chunks.append("Best Bargains\n" + _ocr_text_if_available(original_path))

    if not crops:
        raise ValueError("Upload one combined screenshot or separate Best Sellers / Best Bargains screenshots.")

    ocr_text = "\n".join(chunk for chunk in ocr_chunks if chunk)
    parsed_text_slots = parse_cardmarket_screenshot_text("\n".join([pasted_text, ocr_text]), max_items=9)
    text_by_key = {(slot.category, slot.rank): slot for slot in parsed_text_slots}

    collected_at = utcnow()
    created: list[CardmarketTrend] = []
    for category, rank, image_url in crops:
        text_slot = text_by_key.get((category, rank))
        fallback_label = "Best Seller" if category == "best_sellers" else "Best Bargain"
        trend = CardmarketTrend(
            category=category,
            rank=rank,
            product_name=text_slot.product_name if text_slot else f"Cardmarket {fallback_label} #{rank}",
            expansion=text_slot.expansion if text_slot else None,
            card_number=text_slot.card_number if text_slot else None,
            price=text_slot.price if text_slot else None,
            currency=text_slot.currency if text_slot else "EUR",
            image_url=image_url,
            product_url=None,
            source_url=source_url,
            collected_at=collected_at,
            raw_payload_json=json.dumps(
                {
                    "source": "screenshot_upload",
                    "original_images": original_urls,
                    "ocr_used": bool(ocr_text),
                    "manual_text_used": bool(pasted_text.strip()),
                },
                ensure_ascii=True,
            ),
        )
        created.append(trend)

    day_start = collected_at.replace(hour=0, minute=0, second=0, microsecond=0)
    for category in {category for category, _, _ in crops}:
        CardmarketTrend.query.filter(
            CardmarketTrend.category == category,
            CardmarketTrend.collected_at >= day_start,
        ).delete(synchronize_session=False)
    db.session.add_all(created)
    db.session.commit()
    print(f"[ai_market_intel] CARDMARKET_SCREENSHOT_IMPORTED count={len(created)}", flush=True)
    return len(created)


def import_cardmarket_trends_from_screenshot(
    screenshot: FileStorage,
    *,
    pasted_text: str = "",
    source_url: str = "https://www.cardmarket.com/en/Pokemon",
) -> int:
    return import_cardmarket_trends_from_screenshots(
        combined_screenshot=screenshot,
        pasted_text=pasted_text,
        source_url=source_url,
    )
