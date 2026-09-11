"""Display persisted dataset metadata and field availability."""

import streamlit as st

from ops_workbench.ui.components.common import (
    configure_page,
    dataset_metadata_rows,
    field_availability_rows,
    require_dataset,
)

configure_page("Dataset Status")
snapshot = require_dataset()
if snapshot is not None:
    st.subheader("Dataset metadata")
    st.dataframe(dataset_metadata_rows(snapshot), hide_index=True)
    st.subheader("Field availability")
    st.dataframe(field_availability_rows(snapshot), hide_index=True)
