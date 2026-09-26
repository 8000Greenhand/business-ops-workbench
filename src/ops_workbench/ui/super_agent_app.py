"""Independent Streamlit entry point for the simulated agent operating system."""

import streamlit as st


def main() -> None:
    """Run the agent demo without altering the city supply entry point."""
    page = st.Page("pages/9_super_agent_ops.py", title="超级经纪人运营系统", url_path="super_agent_ops", default=True)
    st.navigation([page], position="hidden").run()


if __name__ == "__main__":
    main()
