import json
import os
from datetime import datetime


DEFAULT_LOG_PATH = os.path.join("logs", "listings.log")
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 7


def rotate_log_if_needed(log_path, max_bytes=DEFAULT_MAX_BYTES, backup_count=DEFAULT_BACKUP_COUNT):
    if max_bytes <= 0:
        return

    if not os.path.exists(log_path):
        return

    try:
        if os.path.getsize(log_path) < max_bytes:
            return

        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        base_dir = os.path.dirname(log_path)
        base_name = os.path.basename(log_path)
        rotated_path = os.path.join(base_dir, f"{base_name}.{timestamp}")

        os.replace(log_path, rotated_path)
        cleanup_old_logs(log_path, backup_count)
    except Exception as e:
        print("Erro ao rodar listing log:", e)


def cleanup_old_logs(log_path, backup_count=DEFAULT_BACKUP_COUNT):
    if backup_count <= 0:
        return

    base_dir = os.path.dirname(log_path)
    base_name = os.path.basename(log_path)
    prefix = base_name + "."

    try:
        backups = []
        for filename in os.listdir(base_dir):
            if not filename.startswith(prefix):
                continue

            path = os.path.join(base_dir, filename)
            if os.path.isfile(path):
                backups.append(path)

        backups.sort(key=os.path.getmtime, reverse=True)

        for old_path in backups[backup_count:]:
            os.remove(old_path)
    except Exception as e:
        print("Erro ao limpar listing logs antigos:", e)


def log_listing_event(
    source,
    title,
    price,
    assessment,
    priority=False,
    consulted_cardmarket=False,
    cardmarket_found=False,
    reject_reason=None,
    log_path=DEFAULT_LOG_PATH,
    max_bytes=DEFAULT_MAX_BYTES,
    backup_count=DEFAULT_BACKUP_COUNT,
):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    rotate_log_if_needed(log_path, max_bytes=max_bytes, backup_count=backup_count)

    is_valid = bool(assessment.is_valid) if assessment else False
    final_reject_reason = reject_reason
    if final_reject_reason is None and assessment:
        final_reject_reason = assessment.reject_reason

    event = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": source,
        "title": title,
        "price": price,
        "category": assessment.category if assessment else "unknown",
        "score": assessment.score if assessment else 0,
        "confidence": assessment.confidence if assessment else "none",
        "is_valid": is_valid and final_reject_reason is None,
        "reject_reason": final_reject_reason,
        "priority": bool(priority),
        "consulted_cardmarket": bool(consulted_cardmarket),
        "cardmarket_found": bool(cardmarket_found),
    }

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print("Erro ao escrever listing log:", e)
