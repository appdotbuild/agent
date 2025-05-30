import streamlit as st
import ujson as json
from pathlib import Path
import anyio
from typing import Dict, List, Any
from datetime import datetime
import os
from analysis.utils import extract_trajectories_from_dump
from trpc_agent.actors import ConcurrentActor, DraftActor
from trpc_agent.silly import EditActor


def find_fsm_files(directory: Path) -> List[Path]:
    """Find all FSM checkpoint files in the given directory."""
    fsm_files = []
    patterns = []
    if st.sidebar.checkbox("FSM enter states", value=False):
        patterns.append("*fsm_enter.json")
    if st.sidebar.checkbox("FSM exit states", value=True):
        patterns.append("*fsm_exit.json")
    for pattern in patterns:
        fsm_files.extend(directory.glob(pattern))
    return sorted(fsm_files, key=lambda x: x.stat().st_mtime, reverse=True)


def display_message(msg: Dict[str, Any], idx: int):
    """Display a single message in a nice format."""
    with st.expander(f"Message {idx + 1}: {msg.get('role', 'Unknown')}", expanded=False):
        content = msg.get('content', [''])
        if isinstance(content, list) and len(content) == 1:
            content = content[0]
        st.json(content)

        # Display additional fields
        excluded_fields = {'role', 'content', 'timestamp'}
        other_fields = {k: v for k, v in msg.items() if k not in excluded_fields}
        if other_fields:
            st.write("**Other fields:**")
            st.json(other_fields)


def truncate_name(s: str):
    name, *rest = s.split('-')
    return "-".join([name[:6] + '...', *rest])

def main():
    st.set_page_config(page_title="FSM Message Analyzer", layout="wide")
    st.title("FSM Message Trajectory Analyzer")

    # Sidebar for file selection
    with st.sidebar:
        st.header("Settings")

        current_dir = os.path.dirname(os.path.abspath(__file__))
        traces_dir = Path(os.path.join(current_dir, "../traces"))
        if not traces_dir.exists():
            st.error(f"Traces directory not found: {traces_dir}")
            return

        fsm_files = find_fsm_files(traces_dir)

        if not fsm_files:
            st.warning("No FSM checkpoint files found in traces directory")
            return

        # File selection
        selected_file = st.selectbox(
            "Select FSM checkpoint file",
            options=fsm_files,
            format_func=lambda x: f"{truncate_name(x.name)} ({datetime.fromtimestamp(x.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')})"
        )

        # Process button
        if st.button("Process File", type="primary"):
            st.session_state.current_file = selected_file
            st.session_state.processing = True

        actors_to_display = st.sidebar.multiselect(
            "Select Actors to Display",
            options=["Frontend", "Handler", "Draft", "Edit"],
            default=["Frontend", "Handler", "Draft", "Edit"]
        )

    # Main content area
    if 'current_file' in st.session_state and st.session_state.get('processing'):
        try:
            with st.spinner(f"Processing {st.session_state.current_file.name}..."):
                messages = extract_trajectories_from_dump(st.session_state.current_file)
                st.session_state.messages = messages
                st.session_state.processing = False
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")
            st.session_state.processing = False

    # Display results
    if 'messages' in st.session_state:
        messages = st.session_state.messages

        # Summary
        st.header("Summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Trajectories", len(messages))
        with col2:
            total_messages = sum(len(msgs) for msgs in messages.values())
            st.metric("Total Messages", total_messages)
        with col3:
            st.metric("File", st.session_state.current_file.name)

        # Trajectory filter
        st.header("Trajectories")

        # Search box
        search_term = st.text_input("Search in messages", placeholder="Enter search term...")

        # Display trajectories
        for trajectory_name, trajectory_messages in messages.items():
            is_displayed = False
            for actor in actors_to_display:
                if trajectory_name.startswith(actor.lower()):
                    is_displayed = True
                    break
            if not is_displayed:
                continue

            # Filter messages if search term is provided
            if search_term:
                filtered_messages = [
                    msg for msg in trajectory_messages
                    if search_term.lower() in str(msg).lower()
                ]
                if not filtered_messages:
                    continue
            else:
                filtered_messages = trajectory_messages

            with st.container():
                st.subheader(f"📍 {trajectory_name}")
                st.write(f"**{len(filtered_messages)} messages**")

                # Display messages
                for idx, msg in enumerate(filtered_messages):
                    display_message(msg, idx)

                st.divider()

    else:
        st.info("👈 Select an FSM checkpoint file from the sidebar to begin analysis")


if __name__ == "__main__":
    main()
