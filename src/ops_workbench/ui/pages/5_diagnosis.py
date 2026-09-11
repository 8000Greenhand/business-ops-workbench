"""Diagnose one anomaly selected from the latest anomaly scan."""

import streamlit as st

from ops_workbench.diagnostics import DiagnosisEngine, EvidenceKind
from ops_workbench.metrics import MetricEngine
from ops_workbench.ui.components.common import configure_page, require_dataset

configure_page("Diagnosis")
snapshot = require_dataset()
events = tuple(st.session_state.get("last_anomaly_events", ()))

if not events:
    st.info("Run an anomaly scan on the Anomalies page, then return here.")
else:
    selected_index = st.selectbox(
        "Anomaly event",
        range(len(events)),
        format_func=lambda index: (
            f"{events[index].date} · {events[index].metric_name} · "
            f"{events[index].dimension}={events[index].dimension_value}"
        ),
    )
    if st.button("Diagnose", type="primary", disabled=snapshot is None):
        result = DiagnosisEngine(MetricEngine()).diagnose_event(events[selected_index])
        st.write(f"Status: {result.status.value}")
        for kind in (
            EvidenceKind.FACT,
            EvidenceKind.DIAGNOSTIC,
            EvidenceKind.RECOMMENDATION,
        ):
            st.subheader(kind.value.title())
            messages = [item.message for item in result.evidence if item.kind == kind]
            if messages:
                for message in messages:
                    st.write(f"- {message}")
            else:
                st.caption("No items.")
        st.subheader("Limitations")
        for limitation in result.limitations:
            st.write(f"- {limitation}")
