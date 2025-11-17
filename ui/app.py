"""Streamlit UI for travel planner - PR-4B.

Run with: streamlit run ui/app.py
"""

# Add project root to sys.path for imports to work when run via streamlit
# Streamlit executes this file as __main__, so ui package isn't automatically available
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]  # Project root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import time  # noqa: E402

import streamlit as st  # noqa: E402

from ui.helpers import (  # noqa: E402
    build_activity_feed,
    build_itinerary_view,
    build_telemetry_view,
    create_run,
    stream_run_events,
)

# Configuration
BACKEND_URL = "http://localhost:8000"

# Page config
st.set_page_config(
    page_title="Travel Planner",
    page_icon="✈️",
    layout="wide",
)

# Initialize session state
if "run_id" not in st.session_state:
    st.session_state.run_id = None
if "events" not in st.session_state:
    st.session_state.events = []
if "run_status" not in st.session_state:
    st.session_state.run_status = None
if "last_heartbeat" not in st.session_state:
    st.session_state.last_heartbeat = None


# Title
st.title("✈️ AI Travel Planner")
st.markdown("*PR-4B: Stub orchestrator with live SSE streaming*")

# Sidebar controls
with st.sidebar:
    st.header("Trip Details")

    prompt = st.text_area(
        "Trip Brief",
        value="Plan a 3-day trip to Paris",
        height=100,
        help="Describe your trip requirements",
    )

    max_days = st.slider("Max Days", min_value=3, max_value=7, value=5)

    budget_usd = st.number_input(
        "Budget (USD)",
        min_value=100,
        max_value=10000,
        value=2500,
        step=100,
    )

    if st.button("🚀 Start Planning", type="primary", use_container_width=True):
        try:
            with st.spinner("Creating run..."):
                result = create_run(
                    BACKEND_URL,
                    prompt=prompt,
                    max_days=max_days,
                    budget_usd_cents=budget_usd * 100,
                )
                st.session_state.run_id = result["run_id"]
                st.session_state.events = []
                st.session_state.run_status = "running"
                st.session_state.last_heartbeat = None
                st.success(f"Run started: {result['run_id'][:8]}...")
                st.rerun()
        except Exception as e:
            st.error(f"Failed to start run: {e}")

    # Display current run
    if st.session_state.run_id:
        st.divider()
        st.caption(f"**Run ID:** `{st.session_state.run_id[:8]}...`")
        if st.session_state.run_status:
            status_color = {
                "running": "🔵",
                "succeeded": "✅",
                "failed": "❌",
                "cancelled": "⚠️",
            }.get(st.session_state.run_status, "⚪")
            st.caption(f"**Status:** {status_color} {st.session_state.run_status}")

        if st.session_state.last_heartbeat:
            st.caption(f"**Last heartbeat:** {st.session_state.last_heartbeat}")

# Main layout - 3 columns
col_left, col_center, col_right = st.columns([2, 3, 2])

with col_left:
    st.subheader("📋 Activity Feed")
    activity_container = st.container(height=600)

    if st.session_state.events:
        feed_items = build_activity_feed(st.session_state.events)
        with activity_container:
            for item in feed_items:
                st.markdown(item)
    else:
        with activity_container:
            st.info("No activity yet. Start a run to see progress.")

with col_center:
    st.subheader("🗺️ Itinerary")
    itinerary_container = st.container(height=600)

    if st.session_state.events:
        itinerary = build_itinerary_view(st.session_state.events)

        with itinerary_container:
            if itinerary["days"]:
                st.markdown(f"**Status:** {itinerary['status']}")
                st.divider()

                for day_info in itinerary["days"]:
                    st.markdown(f"### Day {day_info['day']}")
                    for slot in day_info["slots"]:
                        st.markdown(f"- **{slot['time']}**: {slot['activity']}")
            else:
                st.info("Itinerary will appear here once planning is complete.")
    else:
        with itinerary_container:
            st.info("Itinerary will appear here once planning is complete.")

with col_right:
    st.subheader("🔍 Checks & Tools")
    telemetry_container = st.container(height=600)

    if st.session_state.events:
        telemetry = build_telemetry_view(st.session_state.events)

        with telemetry_container:
            st.markdown(f"**Progress:** {telemetry['checks']}")
            st.divider()

            st.markdown("**Completed:**")
            for node in telemetry["nodes_completed"]:
                st.markdown(f"- ✓ {node}")

            if telemetry["nodes_pending"]:
                st.markdown("**Pending:**")
                for node in telemetry["nodes_pending"]:
                    st.markdown(f"- ⋯ {node}")

            if telemetry["violations"]:
                st.divider()
                st.markdown("**Violations:**")
                for v in telemetry["violations"]:
                    st.markdown(f"- {v}")
    else:
        with telemetry_container:
            st.info("Telemetry will appear here during execution.")

# SSE streaming logic (runs in background)
if st.session_state.run_id and st.session_state.run_status == "running":
    try:
        # Stream events
        for event in stream_run_events(BACKEND_URL, st.session_state.run_id):
            event_type = event["type"]
            event_data = event["data"]

            if event_type == "run_event":
                # Add to events list
                st.session_state.events.append(event_data)

            elif event_type == "heartbeat":
                # Update heartbeat timestamp
                st.session_state.last_heartbeat = event_data.get("ts", "")

            elif event_type == "done":
                # Run completed
                st.session_state.run_status = event_data.get("status", "unknown")
                st.rerun()
                break  # type: ignore[unreachable]

            # Rerun to update UI every 5 events
            if len(st.session_state.events) % 5 == 0:
                time.sleep(0.1)  # Small delay to avoid too many reruns
                st.rerun()

        # Final rerun when stream ends
        st.rerun()

    except Exception as e:
        st.error(f"Stream error: {e}")
        st.session_state.run_status = "failed"
