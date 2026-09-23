"""Small shared helpers for the Streamlit workbench shell."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Iterable

import duckdb
import streamlit as st

from ops_workbench.metrics.engine import MetricGroupResult, MetricResult
from ops_workbench.models.database import (
    DEFAULT_DATABASE_PATH,
    DatasetMetadata,
    FieldAvailability,
    get_dataset_metadata,
    get_field_availability,
)

APP_TITLE = "Business Ops Workbench"


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    """Persisted dataset state used by presentation pages."""

    metadata: DatasetMetadata
    availability: tuple[FieldAvailability, ...]
    quality_status: str = "Validated"


def configure_page(title: str, *, show_heading: bool = True) -> None:
    """Apply shared Streamlit metadata and the enterprise workbench visual system."""
    st.set_page_config(
        page_title=f"{title} | {APP_TITLE}",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _apply_visual_system()
    if show_heading:
        st.title(title)
        st.caption(APP_TITLE)


def render_page_header(title: str, subtitle: str, metadata: Iterable[str] = ()) -> None:
    """Render a compact, consistent dashboard header."""
    tags = "".join(f'<span class="ops-header-meta">{escape(item)}</span>' for item in metadata)
    st.markdown(
        "<section class=\"ops-page-header\">"
        f"<div><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>"
        f"<div class=\"ops-header-meta-row\">{tags}</div>"
        "</section>",
        unsafe_allow_html=True,
    )


def render_section_header(title: str, subtitle: str | None = None, badge: str | None = None) -> None:
    """Render a compact section heading with an optional shared status badge."""
    badge_html = _badge_html(badge) if badge else ""
    subtitle_html = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        "<div class=\"ops-section-heading\">"
        f"<div><h2>{escape(title)}</h2>{subtitle_html}</div>{badge_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def render_metric_card(label: str, value: str, detail: str | None = None, tone: str = "primary") -> None:
    """Render a fixed-height metric card without recalculating the supplied value."""
    detail_html = f"<p>{escape(detail)}</p>" if detail else "<p>&nbsp;</p>"
    st.markdown(
        f"<section class=\"ops-metric-card ops-tone-{escape(tone)}\">"
        f"<div class=\"ops-metric-label\">{escape(label)}</div>"
        f"<div class=\"ops-metric-value\">{escape(value)}</div>{detail_html}"
        "</section>",
        unsafe_allow_html=True,
    )


def render_status_badge(label: str) -> None:
    """Render a small semantic status badge using only presentation mappings."""
    st.markdown(_badge_html(label), unsafe_allow_html=True)


def render_ranked_bars(
    rows: Iterable[tuple[str, object]], *, growth: bool = False
) -> None:
    """Render a compact labelled ranking chart from values already selected by the caller."""
    prepared = [(str(label), _numeric_or_none(value)) for label, value in rows]
    valid = [(label, value) for label, value in prepared if value is not None]
    if not valid:
        st.info("当前没有可展示的数据。")
        return
    maximum = max(abs(value) for _, value in valid) or 1.0
    bars = "".join(
        "<div class=\"ops-ranked-bar\" title=\"{name}\">"
        "<span class=\"ops-ranked-bar__name\">{name}</span>"
        "<span class=\"ops-ranked-bar__track\"><span class=\"ops-ranked-bar__fill\" style=\"width:{width:.1f}%\"></span></span>"
        "<span class=\"ops-ranked-bar__value\">{value}</span>"
        "</div>".format(
            name=escape(label),
            width=abs(value) / maximum * 100,
            value=escape(format_metric_value(value)),
        )
        for label, value in valid
    )
    modifier = " ops-ranked-bars--growth" if growth else ""
    st.markdown(f'<div class="ops-ranked-bars{modifier}">{bars}</div>', unsafe_allow_html=True)


def render_signed_contributions(rows: Iterable[tuple[str, object]]) -> None:
    """Render supplied positive and negative contributions around a zero baseline."""
    prepared = [(str(label), _numeric_or_none(value)) for label, value in rows]
    valid = [(label, value) for label, value in prepared if value is not None]
    if not valid:
        st.info("当前没有可展示的数据。")
        return
    maximum = max(abs(value) for _, value in valid) or 1.0
    items = "".join(
        "<div class=\"ops-contribution-row\">"
        "<span class=\"ops-contribution-label\">{label}</span>"
        "<span class=\"ops-contribution-plot\"><span class=\"ops-contribution-zero\"></span>"
        "<span class=\"ops-contribution-fill ops-contribution-fill--{direction}\" style=\"width:{width:.1f}%\"></span></span>"
        "<span class=\"ops-contribution-value ops-contribution-value--{direction}\">{value}</span>"
        "</div>".format(
            label=escape(label),
            direction="positive" if value >= 0 else "negative",
            width=abs(value) / maximum * 50,
            value=escape(format_currency_delta(value, force_wan=True)),
        )
        for label, value in valid
    )
    st.markdown(f'<div class="ops-contributions">{items}</div>', unsafe_allow_html=True)


def format_currency(value: object, *, compact: bool = False, force_wan: bool = False) -> str:
    """Format a supplied numeric value as a yuan amount while preserving missing values."""
    amount = _numeric_or_none(value)
    if amount is None:
        return "不可用"
    if force_wan or abs(amount) >= 10_000:
        return f"¥{amount / 10_000:.2f}万"
    return f"¥{amount:,.2f}"


def format_delta(value: object, *, percent: bool = False) -> str:
    """Format a signed supplied value with a directional arrow for display."""
    number = _numeric_or_none(value)
    if number is None:
        return "不可用"
    arrow = "↑" if number > 0 else "↓" if number < 0 else "—"
    magnitude = abs(number)
    rendered = f"{magnitude:.1%}" if percent else f"¥{magnitude:,.2f}"
    return f"{arrow} {rendered}" if arrow != "—" else rendered


def format_currency_delta(value: object, *, force_wan: bool = False) -> str:
    """Format a signed amount in business units without changing the supplied value."""
    number = _numeric_or_none(value)
    if number is None:
        return "不可用"
    arrow = "↑" if number > 0 else "↓" if number < 0 else "—"
    rendered = format_currency(abs(number), compact=True, force_wan=force_wan)
    return f"{arrow} {rendered}" if arrow != "—" else rendered


def format_ratio(value: object) -> str:
    """Format a supplied ratio for a table without changing its stored value."""
    number = _numeric_or_none(value)
    if number is None:
        return "不可用"
    return f"{number:+.1%}" if number else "0.0%"


def format_metric_value(value: object) -> str:
    """Format a supplied amount for compact business tables."""
    return format_currency(value, compact=True)


def _numeric_or_none(value: object) -> float | None:
    """Return a finite display number, retaining missing values as unavailable."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _badge_html(label: str) -> str:
    token = label.upper().replace(" ", "-").replace("_", "-")
    palette = {
        "PRIORITY": "negative",
        "ATTENTION": "attention",
        "WATCHLIST": "watchlist",
        "HIGH": "positive",
        "MEDIUM": "attention",
        "LIMITED": "quality",
        "KEY": "primary",
        "MID": "watchlist",
        "LONG-TAIL": "watchlist",
        "UNAVAILABLE": "quality",
        "CONFLICT": "attention",
        "VALID": "positive",
        "高优先级": "negative",
        "需关注": "attention",
        "观察": "watchlist",
        "高可信": "positive",
        "中等可信": "attention",
        "证据有限": "quality",
    }
    return f'<span class="ops-badge ops-badge-{palette.get(token, "neutral")}">{escape(label)}</span>'


def _apply_visual_system() -> None:
    """Inject the lightweight shared CSS used by Dashboard A and Dashboard B."""
    st.markdown(
        """
        <style>
        :root { --ops-bg: #F6F8FB; --ops-card: #FFFFFF; --ops-text: #182230; --ops-muted: #667085;
                --ops-border: #E3E8EF; --ops-blue: #2F6BFF; --ops-green: #168A5B; --ops-red: #C64040;
                --ops-orange: #B75D09; --ops-slate: #536579; }
        .stApp { background: var(--ops-bg); color: var(--ops-text); }
        [data-testid="stHeader"] { background: rgba(246,248,251,.92); border-bottom: 1px solid var(--ops-border); }
        .block-container { max-width: 1540px; padding: 1rem 2.4rem 2.5rem; }
        section[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid var(--ops-border); }
        section[data-testid="stSidebar"] > div { padding-top: 1rem; }
        [data-testid="stSidebar"] label { color: #344054; font-size: .82rem; font-weight: 600; }
        [data-testid="stSidebar"] [data-baseweb="select"] > div { border-color: var(--ops-border); border-radius: 8px; }
        [data-testid="stSidebarNav"] a[href*="ysb_dashboard_a"], [data-testid="stSidebarNav"] a[href*="ysb_dashboard_b"], [data-testid="stSidebarNav"] a[href*="city_supply_ops"] { min-height: 2.2rem; display: flex; align-items: center; color: var(--ops-text) !important; opacity: 1; }
        [data-testid="stSidebarNav"] a[href*="ysb_dashboard_a"] * { font-size: 0 !important; }
        [data-testid="stSidebarNav"] a[href*="ysb_dashboard_a"]:after { content: "区域商家经营"; color: var(--ops-text); font-size: .9rem; font-weight: 600; }
        [data-testid="stSidebarNav"] a[href*="ysb_dashboard_b"] * { font-size: 0 !important; }
        [data-testid="stSidebarNav"] a[href*="ysb_dashboard_b"]:after { content: "单商家经营诊断"; color: var(--ops-text); font-size: .9rem; font-weight: 600; }
        [data-testid="stSidebarNav"] a[href*="city_supply_ops"] * { font-size: 0 !important; }
        [data-testid="stSidebarNav"] a[href*="city_supply_ops"]:after { content: "城市运力经营"; color: var(--ops-text); font-size: .9rem; font-weight: 600; }
        [data-testid="stSidebarNav"] a:not([href*="ysb_dashboard_a"]):not([href*="ysb_dashboard_b"]):not([href*="city_supply_ops"]) { display: none; }
        [data-testid="stSidebarNav"] li:has(a:not([href*="ysb_dashboard_a"]):not([href*="ysb_dashboard_b"]):not([href*="city_supply_ops"])) { display: none; }
        [data-testid="stSidebarNav"]:before { content: "业务看板"; display: block; margin: .25rem .7rem .45rem;
                                                color: var(--ops-muted); font-size: .75rem; font-weight: 700; }
        .ops-page-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 1.5rem;
                            margin: 0 0 .8rem; padding: 0 0 .7rem; border-bottom: 1px solid var(--ops-border); }
        .ops-page-header h1 { margin: 0; color: var(--ops-text); font-size: 1.7rem; letter-spacing: -.025em; }
        .ops-page-header p { margin: .28rem 0 0; color: var(--ops-muted); font-size: .9rem; }
        .ops-header-meta-row { display: flex; gap: .45rem; flex-wrap: wrap; justify-content: flex-end; }
        .ops-header-meta { color: #475467; border: 1px solid var(--ops-border); background: #FFFFFF; border-radius: 6px;
                           padding: .3rem .52rem; font-size: .76rem; white-space: nowrap; }
        .ops-section-heading { display: flex; align-items: center; justify-content: space-between; gap: 1rem;
                               margin: 1.3rem 0 .55rem; }
        .ops-section-heading h2 { color: var(--ops-text); font-size: 1.08rem; margin: 0; letter-spacing: -.01em; }
        .ops-section-heading p { color: var(--ops-muted); margin: .2rem 0 0; font-size: .82rem; }
        .ops-metric-card { min-height: 102px; background: var(--ops-card); border: 1px solid var(--ops-border);
                           border-radius: 10px; box-shadow: 0 1px 2px rgba(16,24,40,.04); padding: .75rem .9rem .65rem;
                           position: relative; overflow: hidden; }
        .ops-metric-card:before { content: ""; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px;
                                  background: var(--ops-blue); border-radius: 0 3px 3px 0; }
        .ops-tone-positive:before { background: var(--ops-green); } .ops-tone-negative:before { background: var(--ops-red); }
        .ops-tone-attention:before { background: var(--ops-orange); } .ops-tone-neutral:before { background: var(--ops-slate); }
        .ops-metric-label { color: var(--ops-muted); font-size: .78rem; font-weight: 600; }
        .ops-metric-value { color: var(--ops-text); font-size: 1.48rem; line-height: 1.25; font-weight: 700; margin-top: .38rem; letter-spacing: -.02em; }
        .ops-metric-card p { color: var(--ops-muted); font-size: .75rem; margin: .35rem 0 0; }
        .ops-diagnosis-summary { color: var(--ops-text); font-size: 1.08rem; font-weight: 650; line-height: 1.65;
                                 max-width: 1050px; margin: .25rem 0 .8rem; }
        .ops-diagnosis-hero { background: #FFFFFF; border: 1px solid var(--ops-border); border-radius: 10px;
                               border-left: 4px solid var(--ops-red); padding: 1rem 1.1rem; margin: .25rem 0 .8rem; }
        .ops-diagnosis-hero h3 { margin: 0; font-size: 1.3rem; color: var(--ops-text); }
        .ops-diagnosis-hero p { margin: .35rem 0 0; color: #475467; font-size: .94rem; }
        .ops-compact-fact { min-height: 112px; padding: .75rem .85rem; }
        .ops-compact-fact strong { color: var(--ops-text); font-size: .83rem; }
        .ops-compact-fact p { margin: .34rem 0 0; color: #475467; font-size: .86rem; line-height: 1.45; }
        .ops-ranked-bars { background: #FFFFFF; border: 1px solid var(--ops-border); border-radius: 8px; padding: .55rem .8rem; }
        .ops-ranked-bar { display: grid; grid-template-columns: minmax(150px, 1.1fr) minmax(180px, 2.4fr) 82px; gap: .65rem;
                          align-items: center; min-height: 29px; font-size: .8rem; }
        .ops-ranked-bar__name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #344054; }
        .ops-ranked-bar__track { height: 10px; background: #F1F4F8; border-radius: 99px; overflow: hidden; }
        .ops-ranked-bar__fill { display: block; height: 100%; background: var(--ops-red); border-radius: 99px; }
        .ops-ranked-bars--growth .ops-ranked-bar__fill { background: var(--ops-green); }
        .ops-ranked-bar__value { text-align: right; color: #344054; font-variant-numeric: tabular-nums; }
        .ops-contributions { background: #FFFFFF; border: 1px solid var(--ops-border); border-radius: 8px; padding: .55rem .8rem; }
        .ops-contribution-row { display: grid; grid-template-columns: 90px minmax(260px, 1fr) 100px; gap: .75rem;
                                align-items: center; min-height: 42px; font-size: .82rem; }
        .ops-contribution-label { color: #344054; font-weight: 600; }
        .ops-contribution-plot { position: relative; height: 18px; background: #F5F7FA; border-radius: 4px; overflow: hidden; }
        .ops-contribution-zero { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: #98A2B3; z-index: 2; }
        .ops-contribution-fill { position: absolute; top: 3px; bottom: 3px; border-radius: 3px; }
        .ops-contribution-fill--positive { left: 50%; background: var(--ops-green); }
        .ops-contribution-fill--negative { right: 50%; background: var(--ops-red); }
        .ops-contribution-value { text-align: right; font-weight: 650; font-variant-numeric: tabular-nums; }
        .ops-contribution-value--positive { color: var(--ops-green); }
        .ops-contribution-value--negative { color: var(--ops-red); }
        .ops-badge { display: inline-flex; align-items: center; border-radius: 5px; padding: .18rem .42rem;
                     font-size: .7rem; font-weight: 700; letter-spacing: .02em; line-height: 1.25; white-space: nowrap; }
        .ops-badge-primary { color: #1D4ED8; background: #EAF0FF; } .ops-badge-positive { color: #12724A; background: #E9F7F0; }
        .ops-badge-negative { color: #A83232; background: #FDECEC; } .ops-badge-attention { color: #965007; background: #FFF4E5; }
        .ops-badge-watchlist { color: #45586B; background: #EEF2F6; } .ops-badge-quality { color: #5C6470; background: #F2F4F7; }
        .ops-badge-neutral { color: #475467; background: #F2F4F7; }
        [data-testid="stVerticalBlockBorderWrapper"] { background: #FFFFFF; border-color: var(--ops-border); border-radius: 10px; box-shadow: 0 1px 2px rgba(16,24,40,.03); }
        [data-testid="stDataFrame"] { border: 1px solid var(--ops-border); border-radius: 8px; overflow: hidden; background: #FFFFFF; }
        [data-testid="stDataFrame"] [role="columnheader"] { background: #F8FAFC; font-weight: 650; }
        [data-testid="stAlert"] { border-radius: 8px; border-color: var(--ops-border); }
        [data-testid="stExpander"] { border-color: var(--ops-border); border-radius: 8px; background: #FFFFFF; }
        [data-testid="stVegaLiteChart"] { background: #FFFFFF; border: 1px solid var(--ops-border); border-radius: 8px; padding: .35rem; }
        hr { border-color: var(--ops-border); margin: 1rem 0; }
        @media (max-width: 1100px) { .block-container { padding: 1.25rem 1.25rem 2.5rem; }
                                      .ops-page-header { align-items: flex-start; flex-direction: column; }
                                      .ops-header-meta-row { justify-content: flex-start; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def load_dataset_snapshot(
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> DatasetSnapshot | None:
    """Return current metadata, or None when no readable dataset exists."""
    path = Path(database_path)
    if not path.is_file():
        return None
    try:
        metadata = get_dataset_metadata(database_path=path)
        availability = get_field_availability(database_path=path)
    except (duckdb.Error, LookupError, OSError):
        return None
    return DatasetSnapshot(metadata, availability)


def require_dataset() -> DatasetSnapshot | None:
    """Render the standard empty state and return the current snapshot."""
    snapshot = load_dataset_snapshot()
    if snapshot is None:
        st.info("No dataset loaded")
    return snapshot


def dataset_metadata_rows(snapshot: DatasetSnapshot) -> list[dict[str, object]]:
    """Serialize dataset metadata for a plain Streamlit table."""
    return [
        {
            "dataset_id": snapshot.metadata.dataset_id,
            "loaded_at": snapshot.metadata.loaded_at,
            "row_count": snapshot.metadata.row_count,
            "quality_status": snapshot.quality_status,
        }
    ]


def field_availability_rows(
    snapshot: DatasetSnapshot,
) -> list[dict[str, object]]:
    """Serialize canonical field availability for presentation."""
    return [
        {
            "canonical_field": item.canonical_field,
            "available": item.is_available,
            "source_field": item.source_field,
        }
        for item in snapshot.availability
    ]


def metric_result_row(result: MetricResult) -> dict[str, object]:
    """Serialize a structured metric result without recalculating it."""
    return {
        "metric_id": result.metric_id,
        "name": result.name,
        "value": _display_value(result.value),
        "status": result.status.value,
        "format": result.format,
        "numerator": _display_value(result.numerator_value),
        "denominator": _display_value(result.denominator_value),
        "reason": result.reason,
    }


def grouped_metric_rows(
    results: tuple[MetricGroupResult, ...],
) -> list[dict[str, object]]:
    """Serialize grouped metric results for a plain table."""
    return [
        {
            "dimension": result.dimension,
            "dimension_value": result.dimension_value,
            "metric_id": result.metric_id,
            "value": _display_value(result.value),
            "status": result.status.value,
            "reason": result.reason,
        }
        for result in results
    ]


def _display_value(value: int | Decimal | None) -> int | str | None:
    if isinstance(value, Decimal):
        return str(value)
    return value
