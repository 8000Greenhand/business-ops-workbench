"""Identify Dashboard B upload roles from CSV/XLSX table signatures."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import pandas as pd

from ops_workbench.diagnostics.ysb_merchant_b1 import SOURCE_COLUMNS

RAW_ORDER_REQUIRED = frozenset({"下单时间", "订单ID", "进货金额", "商品编码", "产品名称"})
TRAFFIC_REQUIRED = frozenset(
    {
        "时间",
        "详情点击数-我的店铺",
        "详情点击数-同行均值",
        "店铺访客数-我的店铺",
        "店铺访客数-同行均值",
        "活动曝光数-我的店铺",
        "活动曝光数-同行均值",
    }
)
ACTIVITY_REQUIRED = frozenset({"活动ID", "活动类型"})
LEGACY_SHEET = "订单原始数据"
LEGACY_REQUIRED = frozenset(SOURCE_COLUMNS)


@dataclass(frozen=True, slots=True)
class UploadedPayload:
    """One uploaded file before role recognition."""

    name: str
    content: bytes


@dataclass(frozen=True, slots=True)
class RecognizedInputs:
    """Recognized Dashboard B inputs and non-blocking unknown files."""

    order: pd.DataFrame | None
    order_label: str | None
    traffic: pd.DataFrame | None
    traffic_label: str | None
    activities: tuple[pd.DataFrame, ...]
    activity_labels: tuple[str, ...]
    legacy: UploadedPayload | None
    unknown_labels: tuple[str, ...]


def recognize_uploaded_inputs(payloads: Iterable[UploadedPayload]) -> RecognizedInputs:
    """Read uploads and identify their roles from populated column signatures."""
    orders: list[tuple[str, pd.DataFrame]] = []
    traffic_tables: list[tuple[str, pd.DataFrame]] = []
    activity_tables: list[tuple[str, pd.DataFrame]] = []
    legacy_files: list[UploadedPayload] = []
    unknown: list[str] = []

    for payload in payloads:
        if not payload.content:
            unknown.append(payload.name)
            continue
        suffix = Path(payload.name).suffix.lower()
        if suffix == ".csv":
            frame = _read_csv(payload)
            role = detect_table_role(frame)
            _append_role(role, payload.name, frame, orders, traffic_tables, activity_tables, unknown)
            continue
        if suffix == ".xlsx":
            tables, is_legacy = _read_xlsx(payload)
            if is_legacy:
                legacy_files.append(payload)
                continue
            matched = False
            for label, frame in tables:
                role = detect_table_role(frame)
                if role is not None:
                    matched = True
                _append_role(role, label, frame, orders, traffic_tables, activity_tables, unknown)
            if not tables:
                unknown.append(payload.name)
            elif not matched:
                unknown = [label for label in unknown if not label.startswith(f"{payload.name} · ")]
                unknown.append(payload.name)
            continue
        unknown.append(payload.name)

    if len(legacy_files) > 1:
        raise ValueError("识别到多个 legacy 药师帮日报，请只保留一个订单来源。")
    if legacy_files and orders:
        raise ValueError("同时识别到 legacy 日报和原始订单明细，请只保留一个订单来源。")
    if len(orders) > 1:
        labels = "、".join(label for label, _ in orders)
        raise ValueError(f"识别到多个订单明细：{labels}。请只上传一个订单来源。")
    if len(traffic_tables) > 1:
        labels = "、".join(label for label, _ in traffic_tables)
        raise ValueError(f"识别到多个流量文件：{labels}。请只上传一个流量来源。")

    order_label, order = orders[0] if orders else (None, None)
    traffic_label, traffic = traffic_tables[0] if traffic_tables else (None, None)
    return RecognizedInputs(
        order=order,
        order_label=order_label,
        traffic=traffic,
        traffic_label=traffic_label,
        activities=tuple(frame for _, frame in activity_tables),
        activity_labels=tuple(label for label, _ in activity_tables),
        legacy=legacy_files[0] if legacy_files else None,
        unknown_labels=tuple(dict.fromkeys(unknown)),
    )


def detect_table_role(frame: pd.DataFrame) -> str | None:
    """Return the business role supported by one populated table."""
    if _has_populated(frame, RAW_ORDER_REQUIRED):
        return "order"
    if _has_populated(frame, TRAFFIC_REQUIRED):
        return "traffic"
    if _has_populated(frame, ACTIVITY_REQUIRED):
        return "activity"
    return None


def _read_csv(payload: UploadedPayload) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return _clean_frame(pd.read_csv(BytesIO(payload.content), encoding=encoding, dtype="string"))
        except UnicodeDecodeError as error:
            last_error = error
    raise ValueError(f"无法识别 CSV 编码：{payload.name}") from last_error


def _read_xlsx(payload: UploadedPayload) -> tuple[list[tuple[str, pd.DataFrame]], bool]:
    workbook = pd.ExcelFile(BytesIO(payload.content), engine="openpyxl")
    if LEGACY_SHEET in workbook.sheet_names:
        headers = pd.read_excel(workbook, sheet_name=LEGACY_SHEET, nrows=0).columns
        if LEGACY_REQUIRED.issubset({_clean_text(column) for column in headers}):
            return [], True
    tables = []
    for sheet_name in workbook.sheet_names:
        frame = _clean_frame(pd.read_excel(workbook, sheet_name=sheet_name, dtype=str))
        tables.append((f"{payload.name} · {sheet_name}", frame))
    return tables, False


def _append_role(
    role: str | None,
    label: str,
    frame: pd.DataFrame,
    orders: list[tuple[str, pd.DataFrame]],
    traffic_tables: list[tuple[str, pd.DataFrame]],
    activity_tables: list[tuple[str, pd.DataFrame]],
    unknown: list[str],
) -> None:
    if role == "order":
        orders.append((label, frame))
    elif role == "traffic":
        traffic_tables.append((label, frame))
    elif role == "activity":
        activity_tables.append((label, frame))
    else:
        unknown.append(label)


def _has_populated(frame: pd.DataFrame, required: frozenset[str]) -> bool:
    if not required.issubset(frame.columns):
        return False
    return all(_populated(frame[column]).any() for column in required)


def _populated(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype("string").str.strip().ne("")


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [_clean_text(column) for column in result.columns]
    for column in result.columns:
        if result[column].dtype == object or isinstance(result[column].dtype, pd.StringDtype):
            result[column] = result[column].map(_clean_text)
    return result


def _clean_text(value: object) -> object:
    return value.strip() if isinstance(value, str) else value
