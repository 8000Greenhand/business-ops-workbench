"""Calculate registered metrics through MetricEngine."""

from datetime import date, timedelta

import streamlit as st

from ops_workbench.metrics import MetricEngine, MetricRegistry
from ops_workbench.models.canonical_schema import DIMENSION_FIELDS
from ops_workbench.ui.components.common import (
    configure_page,
    grouped_metric_rows,
    metric_result_row,
    require_dataset,
)

configure_page("Metrics")
snapshot = require_dataset()

registry = MetricRegistry.from_yaml()
metric_id = st.selectbox("Metric", [item.id for item in registry.all()])
default_end = date.today()
default_start = default_end - timedelta(days=30)
date_range = st.date_input("Date range", value=(default_start, default_end))
group_by = st.selectbox("Group by", ["Overall", *DIMENSION_FIELDS])

if st.button("Calculate", type="primary", disabled=snapshot is None):
    if not isinstance(date_range, tuple) or len(date_range) != 2:
        st.warning("Select a start and end date.")
    else:
        start_date, end_date = date_range
        engine = MetricEngine()
        if group_by == "Overall":
            result = engine.calculate_metric(
                metric_id,
                start_date=start_date,
                end_date=end_date,
            )
            st.dataframe([metric_result_row(result)], hide_index=True)
        else:
            results = engine.calculate_metric_by_dimension(
                metric_id,
                group_by,
                start_date=start_date,
                end_date=end_date,
            )
            st.dataframe(grouped_metric_rows(results), hide_index=True)
