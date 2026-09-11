"""Streamlit entry point for the operations workbench shell."""

import streamlit as st

from ops_workbench.ui.components.common import (
    APP_TITLE,
    dataset_metadata_rows,
    load_dataset_snapshot,
)


def main() -> None:
    """Render the workbench landing page and current dataset state."""
    st.set_page_config(page_title=APP_TITLE, page_icon="📊")
    st.title(APP_TITLE)
    st.caption("经营诊断工作台 · v0.1.0")
    st.write("Local operations analysis workspace")

    st.subheader("Current dataset")
    snapshot = load_dataset_snapshot()
    if snapshot is None:
        st.info("No dataset loaded")
        return
    st.dataframe(dataset_metadata_rows(snapshot), hide_index=True)


if __name__ == "__main__":
    main()
