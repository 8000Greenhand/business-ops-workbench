"""Upload and preview a local CSV or XLSX without persisting it."""

from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

from ops_workbench.ingestion.file_loader import preview_source
from ops_workbench.ui.components.common import configure_page

configure_page("Data Import")
st.write("Preview a CSV or XLSX source before mapping and import.")

uploaded = st.file_uploader("Source file", type=["csv", "xlsx"])
if uploaded is None:
    st.info("Choose a CSV or XLSX file to preview.")
else:
    safe_name = Path(uploaded.name).name
    st.dataframe(
        [
            {
                "file_name": safe_name,
                "size_bytes": uploaded.size,
                "file_type": Path(safe_name).suffix.lower().removeprefix("."),
            }
        ],
        hide_index=True,
    )
    try:
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory) / safe_name
            temporary_path.write_bytes(uploaded.getvalue())
            loaded = preview_source(temporary_path)
        st.subheader("Preview")
        st.dataframe(loaded.dataframe, hide_index=True)
        st.caption(
            f"Detected {loaded.metadata.column_count} columns. "
            "This preview has not been imported."
        )
    except Exception as error:
        st.error(f"Unable to preview file: {error}")
