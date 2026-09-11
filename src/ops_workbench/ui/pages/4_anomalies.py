"""Scan one date for configured business anomaly events."""

from datetime import date
from decimal import Decimal

import streamlit as st

from ops_workbench.diagnostics import AnomalyEngine
from ops_workbench.metrics import MetricEngine
from ops_workbench.ui.components.common import configure_page, require_dataset


def _value(value: object) -> object:
    return str(value) if isinstance(value, Decimal) else value


configure_page("Anomalies")
snapshot = require_dataset()
scan_date = st.date_input("Scan date", value=date.today())

if st.button("Scan", type="primary", disabled=snapshot is None):
    result = AnomalyEngine(MetricEngine()).scan_date(scan_date)
    st.session_state["last_anomaly_events"] = result.events
    if not result.events:
        st.info("No anomaly events for this date.")
    else:
        st.dataframe(
            [
                {
                    "severity": event.severity.value,
                    "metric": event.metric_id,
                    "dimension": event.dimension,
                    "value": event.dimension_value,
                    "change": _value(event.relative_change),
                }
                for event in result.events
            ],
            hide_index=True,
        )
