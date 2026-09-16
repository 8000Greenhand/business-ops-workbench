"""Streamlit entry point for the operations workbench shell."""

import streamlit as st

from ops_workbench.ui.components.common import (
    APP_TITLE,
    dataset_metadata_rows,
    load_dataset_snapshot,
)


def render_developer_home() -> None:
    """Render the existing application shell inside the developer-tools group."""
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


def main() -> None:
    """Route the formal business workbench with explicit, reversible page links."""
    dashboard_a = st.Page(
        "pages/6_ysb_dashboard_a.py",
        title="区域商家经营",
        url_path="ysb_dashboard_a",
        default=True,
    )
    dashboard_b = st.Page(
        "pages/7_ysb_dashboard_b.py",
        title="单商家经营诊断",
        url_path="ysb_dashboard_b",
    )

    page = st.navigation([dashboard_a, dashboard_b], position="hidden")

    with st.sidebar:
        st.markdown("#### 业务看板")
        st.page_link(dashboard_a, label="区域商家经营", use_container_width=True)
        st.page_link(dashboard_b, label="单商家经营诊断", use_container_width=True)
        st.divider()

    page.run()


if __name__ == "__main__":
    main()
