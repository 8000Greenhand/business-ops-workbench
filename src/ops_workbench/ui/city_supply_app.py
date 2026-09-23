"""Standalone Streamlit entry point for the city supply operations demo."""

import streamlit as st


def main() -> None:
    """Run the city supply dashboard as an independent application."""
    city_supply = st.Page(
        "pages/8_city_supply_ops.py",
        title="城市运力经营",
        url_path="city_supply_ops",
        default=True,
    )
    page = st.navigation([city_supply], position="hidden")
    page.run()


if __name__ == "__main__":
    main()
