"""Streamlit UI for travel planner - PR-12 hero /qa/plan UI.

Run with: streamlit run ui/app.py
"""

# Add project root to sys.path for imports to work when run via streamlit
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from datetime import date, datetime  # noqa: E402

import streamlit as st  # noqa: E402

from ui.helpers import call_qa_plan  # noqa: E402

# Configuration
BACKEND_URL = "http://localhost:8000"

# Page config
st.set_page_config(
    page_title="AI Travel Planner",
    page_icon="✈️",
    layout="wide",
)

# Initialize session state
if "response" not in st.session_state:
    st.session_state.response = None
if "error" not in st.session_state:
    st.session_state.error = None
if "loading" not in st.session_state:
    st.session_state.loading = False

# Title
st.title("✈️ AI Travel Planner")
st.markdown("*Single-shot planning powered by /qa/plan endpoint*")
st.divider()

# Main layout - 3 columns
col_left, col_center, col_right = st.columns([1, 2, 1.5])

# =============================================================================
# LEFT COLUMN - TRIP SETUP FORM
# =============================================================================
with col_left:
    st.subheader("📋 Trip Setup")

    with st.form("trip_form"):
        city = st.text_input("Destination City *", value="Paris", help="Required")

        col_date1, col_date2 = st.columns(2)
        with col_date1:
            start_date = st.date_input(
                "Start Date *", value=date(2025, 6, 10), help="Required"
            )
        with col_date2:
            end_date = st.date_input("End Date *", value=date(2025, 6, 14), help="Required")

        budget = st.number_input(
            "Budget (USD) *",
            min_value=100,
            max_value=50000,
            value=2000,
            step=100,
            help="Required",
        )

        airports_raw = st.text_input(
            "Airports",
            value="JFK",
            help="Comma-separated airport codes (e.g., JFK, LGA, EWR)",
        )

        themes_raw = st.text_input(
            "Themes",
            value="art, food",
            help="Comma-separated themes (e.g., art, food, culture)",
        )

        # Timezone selection
        timezone = st.selectbox(
            "Timezone",
            options=["UTC", "America/New_York", "Europe/Paris", "Asia/Tokyo"],
            index=2,
        )

        submitted = st.form_submit_button("🚀 Plan Trip", type="primary", use_container_width=True)

        # Validation and submission
        if submitted:
            # Basic validation
            errors = []
            if not city.strip():
                errors.append("City is required")
            if not start_date:
                errors.append("Start date is required")
            if not end_date:
                errors.append("End date is required")
            if end_date < start_date:
                errors.append("End date must be after start date")
            if budget < 100:
                errors.append("Budget must be at least $100")

            if errors:
                st.session_state.error = " | ".join(errors)
                st.session_state.response = None
            else:
                # Parse airports and themes
                airports = [a.strip() for a in airports_raw.split(",") if a.strip()]
                themes = [t.strip() for t in themes_raw.split(",") if t.strip()]

                # Call /qa/plan
                st.session_state.loading = True
                st.session_state.error = None
                st.session_state.response = None

                try:
                    response = call_qa_plan(
                        backend_url=BACKEND_URL,
                        city=city.strip(),
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        budget_usd_cents=int(budget * 100),
                        airports=airports,
                        themes=themes,
                        timezone=timezone,
                    )
                    st.session_state.response = response
                    st.session_state.error = None
                except Exception as e:
                    st.session_state.error = str(e)
                    st.session_state.response = None
                finally:
                    st.session_state.loading = False
                    st.rerun()

    # Show validation errors
    if st.session_state.error and not st.session_state.loading:
        st.error(f"❌ {st.session_state.error}")

    # Show loading state
    if st.session_state.loading:
        st.info("⏳ Planning your trip...")

# =============================================================================
# CENTER COLUMN - ANSWER + ITINERARY
# =============================================================================
with col_center:
    st.subheader("🗺️ Your Itinerary")

    if st.session_state.response:
        response = st.session_state.response

        # Render answer markdown
        st.markdown("### Summary")
        st.markdown(response.get("answer_markdown", "_No answer available_"))

        st.divider()

        # Render itinerary
        itinerary = response.get("itinerary", {})
        days = itinerary.get("days", [])
        total_cost = itinerary.get("total_cost_usd", 0)

        if days:
            st.markdown(f"### Days ({len(days)} day{'s' if len(days) != 1 else ''})")
            st.caption(f"**Total Cost:** ${total_cost}")

            for day_info in days:
                day_date = day_info.get("date", "Unknown")
                items = day_info.get("items", [])

                # Parse date for prettier display
                try:
                    parsed_date = datetime.fromisoformat(day_date)
                    display_date = parsed_date.strftime("%A, %B %d, %Y")
                except (ValueError, TypeError):
                    display_date = day_date

                st.markdown(f"#### {display_date}")

                for item in items:
                    start_time = item.get("start", "")
                    end_time = item.get("end", "")
                    title = item.get("title", "Activity")
                    location = item.get("location")
                    notes = item.get("notes", "")

                    time_range = f"{start_time}–{end_time}" if start_time and end_time else ""

                    item_text = f"**{time_range}** {title}"
                    if location:
                        item_text += f" @ _{location}_"
                    if notes:
                        item_text += f"\n  - {notes}"

                    st.markdown(f"- {item_text}")
        else:
            st.info("No itinerary days found.")
    else:
        st.info("👈 Fill out the trip form and hit **Plan Trip** to see your itinerary here.")

# =============================================================================
# RIGHT COLUMN - CHECKS & TELEMETRY
# =============================================================================
with col_right:
    st.subheader("🔍 Checks & Telemetry")

    if st.session_state.response:
        response = st.session_state.response

        # --- VIOLATIONS ---
        violations = response.get("violations", [])
        has_blocking = response.get("has_blocking_violations", False)

        st.markdown("#### Violations")
        if not violations:
            st.success("✅ No issues detected")
        else:
            if has_blocking:
                st.error("🚨 **BLOCKING ISSUES DETECTED**")

            for v in violations:
                severity = v.get("severity", "unknown").upper()
                code = v.get("code", "UNKNOWN")
                message = v.get("message", "")
                kind = v.get("kind", "").upper()
                details = v.get("details", {})

                # Color code severity
                if severity == "BLOCKING":
                    badge = "🔴 BLOCKING"
                elif severity == "ADVISORY":
                    badge = "🟡 ADVISORY"
                else:
                    badge = f"⚪ {severity}"

                st.markdown(f"**{badge}** `{code}` ({kind})")
                st.caption(message)

                # Show key details if present
                if "budget_usd_cents" in details and "total_usd_cents" in details:
                    budget = details["budget_usd_cents"] / 100
                    total = details["total_usd_cents"] / 100
                    ratio = details.get("ratio", total / budget if budget > 0 else 0)
                    st.caption(f"💰 Spent {ratio:.2f}× budget (${total:.2f} vs ${budget:.2f})")

        st.divider()

        # --- TOOLS USED ---
        tools_used = response.get("tools_used", [])

        st.markdown("#### Tools Used")
        if tools_used:
            for tool in tools_used:
                tool_name = tool.get("name", "unknown")
                count = tool.get("count", 0)
                total_ms = tool.get("total_ms", 0)

                st.markdown(f"- **{tool_name}**: {count} call{'s' if count != 1 else ''} ({total_ms}ms)")
        else:
            st.caption("_No tool usage data_")

        st.divider()

        # --- CITATIONS ---
        citations = response.get("citations", [])

        st.markdown("#### Citations")
        if citations:
            for citation in citations:
                claim = citation.get("claim", "")
                prov = citation.get("provenance", {})
                source = prov.get("source", "unknown")
                ref_id = prov.get("ref_id", "")

                badge_text = f"`{source}`"
                if ref_id:
                    badge_text += f" #{ref_id}"

                st.markdown(f"- {claim}")
                st.caption(f"  {badge_text}")
        else:
            st.caption("_No citations_")

        # --- RAW JSON (dev toggle) ---
        with st.expander("🔧 Raw JSON Response (dev)"):
            st.json(response)

    else:
        st.info("Telemetry will appear here after planning.")
