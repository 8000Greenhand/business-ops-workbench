"""Streamlit entry point for the M0 application shell."""

import streamlit as st

APP_TITLE = "Business Ops Workbench"
APP_SUBTITLE = "经营诊断工作台"
APP_VERSION_LABEL = "当前版本：M0 工程底座"


def main() -> None:
    """Render the M0 landing page."""
    st.set_page_config(page_title=APP_TITLE, page_icon="📊")
    st.title(APP_TITLE)
    st.subheader(APP_SUBTITLE)
    st.write(APP_VERSION_LABEL)


if __name__ == "__main__":
    main()
