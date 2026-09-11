from __future__ import annotations

import csv
import hashlib
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "绩效与商家销售额汇总"
OUT_DIR = ROOT / "docs" / "discovery" / "ysb"

ENTITY_TERMS = {
    "merchant_supplier": ["商家", "供应商", "商业", "三方商家", "直供商家", "公司"],
    "purchasing_customer": ["药店", "终端", "客户", "采购客户", "采购方"],
    "product": ["商品", "药品", "SKU", "SPU", "品种", "批准文号", "厂家", "品牌"],
    "activity": ["活动", "包邮", "一口价", "拼团", "批购", "活动ID", "活动类型"],
    "region": ["省", "市", "区域", "战区", "省区", "大区"],
    "operator": ["运营", "商务", "负责人", "BD", "业务员", "跟进人"],
}
METRIC_TERMS = ["GMV", "销售额", "销售金额", "支付金额", "实付金额", "成交金额", "采购金额", "订单", "数量", "客单", "目标", "完成"]
DATE_RE = re.compile(r"(20\d{2})[年./_-]?(\d{1,2})[月./_-]?(\d{1,2})?")


def mask(value: object) -> str:
    text = str(value).strip()
    if not text:
        return ""
    if re.search(r"1\d{10}", text):
        return "<PHONE_MASKED>"
    if re.search(r"\d{17}[0-9Xx]", text):
        return "<ID_MASKED>"
    if len(text) > 40:
        return text[:37] + "..."
    return text


def version_group(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"\s*\(\d+\)", "", stem)
    stem = re.sub(r"20\d{2}[年_-]?\d{0,2}[月_-]?\d{0,2}", "DATE", stem)
    stem = re.sub(r"\d{6,}", "NUM", stem)
    return stem[:100]


def parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    match = DATE_RE.search(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3) or 1))
    except ValueError:
        return None


def is_date_header(header: str) -> bool:
    lowered = header.lower()
    return any(term in lowered for term in ("日期", "时间", "月份", "月份", "date", "month", "day", "dt"))


def header_kind(header: str) -> tuple[str, str]:
    entities = [key for key, terms in ENTITY_TERMS.items() if any(term.lower() in header.lower() for term in terms)]
    metrics = [term for term in METRIC_TERMS if term.lower() in header.lower()]
    return ";".join(entities), ";".join(metrics)


def profile_sheet(path: Path, ws) -> tuple[dict, list[dict]]:
    rows = ws.iter_rows(values_only=True)
    first = next(rows, ())
    headers = [str(v).strip() if v is not None else "" for v in first]
    headers = [h or f"<blank_{i + 1}>" for i, h in enumerate(headers)]
    stats = [{"non_null": 0, "unique": set(), "dates": [], "samples": [], "duplicates": 0} for _ in headers]
    row_count = 0
    seen = Counter()
    has_formula = False
    preview = []
    for row in rows:
        values = list(row[: len(headers)]) + [None] * max(0, len(headers) - len(row))
        values = values[: len(headers)]
        row_count += 1
        key = tuple(str(v) for v in values)
        seen[key] += 1
        if len(preview) < 3:
            preview.append([mask(v) for v in values])
        for idx, value in enumerate(values):
            if isinstance(value, str) and value.startswith("="):
                has_formula = True
            if value not in (None, ""):
                stats[idx]["non_null"] += 1
                stats[idx]["unique"].add(str(value))
                if len(stats[idx]["samples"]) < 3:
                    stats[idx]["samples"].append(mask(value))
                parsed = parse_date(value) if (is_date_header(headers[idx]) or isinstance(value, (date, datetime))) else None
                if parsed:
                    stats[idx]["dates"].append(parsed)
    duplicate_rows = sum(count - 1 for count in seen.values() if count > 1)
    field_rows = []
    for header, stat in zip(headers, stats):
        entity, metric = header_kind(header)
        dates = stat["dates"]
        field_rows.append({
            "file": str(path.relative_to(ROOT)),
            "sheet": ws.title,
            "field": header,
            "dtype": "date_candidate" if dates else "text_or_mixed",
            "non_null_rate": f"{stat['non_null'] / row_count:.4f}" if row_count else "0",
            "unique_count": len(stat["unique"]),
            "sample_values_masked": " | ".join(stat["samples"]),
            "possible_entity": entity,
            "possible_metric": metric,
            "notes": f"date_range={min(dates) if dates else ''}..{max(dates) if dates else ''}",
        })
    profile = {
        "file_name": path.name,
        "relative_path": str(path.relative_to(ROOT)),
        "file_type": path.suffix.lower().lstrip("."),
        "file_size": path.stat().st_size,
        "modified_time": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "possible_version_group": version_group(path.name),
        "read_status": "READABLE",
        "sheet": ws.title,
        "rows": row_count,
        "columns": len(headers),
        "fields": " | ".join(headers),
        "preview_masked": " || ".join(" | ".join(r) for r in preview),
        "date_candidates": " | ".join(h for h, s in zip(headers, stats) if s["dates"]),
        "date_range": " | ".join(f"{h}:{min(s['dates'])}..{max(s['dates'])}" for h, s in zip(headers, stats) if s["dates"]),
        "possible_grain": "unknown_pending_business_confirmation",
        "candidate_keys": " | ".join(h for h, s in zip(headers, stats) if h.lower().endswith(("id", "编码", "编号")) or "编码" in h),
        "duplicate_rows": duplicate_rows,
        "has_formula": has_formula,
        "notes": "Workbook sheet profiled locally; no source rows copied to output.",
    }
    return profile, field_rows


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    inventory: list[dict] = []
    fields: list[dict] = []
    if not DATA_DIR.exists():
        raise SystemExit(f"DATA_DIR_NOT_FOUND: {DATA_DIR}")
    for path in sorted(DATA_DIR.rglob("*")):
        if not path.is_file():
            continue
        entry = {
            "file_name": path.name,
            "relative_path": str(path.relative_to(ROOT)),
            "file_type": path.suffix.lower().lstrip(".") or "[none]",
            "file_size": path.stat().st_size,
            "modified_time": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            "possible_version_group": version_group(path.name),
            "read_status": "INVENTORY_ONLY",
            "sheet": "",
            "rows": "",
            "columns": "",
            "fields": "",
            "preview_masked": "",
            "date_candidates": "",
            "date_range": "",
            "possible_grain": "",
            "candidate_keys": "",
            "duplicate_rows": "",
            "has_formula": "",
            "notes": "Metadata inventory only; non-spreadsheet content not parsed in this pass.",
        }
        if path.suffix.lower() == ".xlsx":
            try:
                wb = load_workbook(path, read_only=True, data_only=False)
                for ws in wb.worksheets:
                    profile, field_rows = profile_sheet(path, ws)
                    inventory.append(profile)
                    fields.extend(field_rows)
                wb.close()
                continue
            except Exception as exc:  # noqa: BLE001
                entry["read_status"] = "UNREADABLE"
                entry["notes"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        inventory.append(entry)

    inv_fields = list(inventory[0].keys()) if inventory else []
    with (OUT_DIR / "YSB_DATA_INVENTORY.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=inv_fields)
        writer.writeheader()
        writer.writerows(inventory)
    field_fields = ["file", "sheet", "field", "dtype", "non_null_rate", "unique_count", "sample_values_masked", "possible_entity", "possible_metric", "notes"]
    with (OUT_DIR / "YSB_FIELD_CATALOG.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=field_fields)
        writer.writeheader()
        writer.writerows(fields)

    groups: dict[str, list[dict]] = {}
    for row in inventory:
        groups.setdefault(row["possible_version_group"], []).append(row)
    with (OUT_DIR / "YSB_DUPLICATE_VERSION_MAP.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        keys = ["version_group", "file_name", "date_or_version", "rows", "columns", "date_range", "likely_latest", "relationship"]
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for group, members in groups.items():
            for row in members:
                writer.writerow({"version_group": group, "file_name": row["file_name"], "date_or_version": "", "rows": row["rows"], "columns": row["columns"], "date_range": row["date_range"], "likely_latest": "UNCONFIRMED", "relationship": "same_structure_or_related_name;manual_confirmation_required" if len(members) > 1 else "single_observed_file"})

    print(f"files={len({r['relative_path'] for r in inventory})} sheet_profiles={len(inventory)} fields={len(fields)}")
    print(f"output={OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
