import streamlit as st
import ujson as json
from pathlib import Path
import anyio
from typing import Dict, List, Any
from datetime import datetime

from analyze import _get_actors, get_all_trajectories
from trpc_agent.actors import ConcurrentActor, DraftActor
from trpc_agent.silly import EditActor


def find_fsm_files(directory: Path) -> List[Path]:
    """Find all FSM checkpoint files in the given directory."""
    fsm_files = []
    for pattern in ["*fsm_enter.json", "*fsm_exit.json"]:
        fsm_files.extend(directory.glob(pattern))
    return sorted(fsm_files, key=lambda x: x.stat().st_mtime, reverse=True)


def process_fsm_file(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Process a single FSM file and extract message trajectories."""
    actors = anyio.run(_get_actors, str(path))
    messages = {}

    for actor in actors:
        match actor:
            case ConcurrentActor():
                handlers = actor.handlers
                for name, handler in handlers.handlers.items():
                    for k, v in get_all_trajectories(handler, f"backend_{name}"):
                        messages[k] = v

                frontend = actor.frontend.root
                if frontend:
                    for k, v in get_all_trajectories(frontend, "frontend"):
                        messages[k] = v

            case DraftActor():
                root = actor.root
                if root is None:
                    continue
                for k, v in get_all_trajectories(root, "draft"):
                    messages[k] = v

            case EditActor():
                root = actor.root
                if root is None:
                    continue
                for k, v in get_all_trajectories(root, "edit"):
                    messages[k] = v

            case _:
                st.error(f"Unknown actor type: {type(actor)}")

    return messages


def display_message(msg: Dict[str, Any], idx: int):
    """Display a single message in a nice format."""
    with st.expander(f"Message {idx + 1}: {msg.get('role', 'Unknown')}", expanded=False):
        content = msg.get('content', '')
        if isinstance(content, str):
            if len(content) > 500:
                st.text_area("Content", content, height=200)
            else:
                st.write("**Content:**", content)
        else:
            st.json(content)

        # Display additional fields
        excluded_fields = {'role', 'content', 'timestamp'}
        other_fields = {k: v for k, v in msg.items() if k not in excluded_fields}
        if other_fields:
            st.write("**Other fields:**")
            st.json(other_fields)


def main():
    st.set_page_config(page_title="FSM Message Analyzer", layout="wide")
    st.title("FSM Message Trajectory Analyzer")

    # Sidebar for file selection
    with st.sidebar:
        st.header("Settings")

        # Directory selection
        traces_dir = Path("/Users/arseny/dev/bot-new/agent/traces")
        if not traces_dir.exists():
            st.error(f"Traces directory not found: {traces_dir}")
            return

        # Find FSM files
        fsm_files = find_fsm_files(traces_dir)

        if not fsm_files:
            st.warning("No FSM checkpoint files found in traces directory")
            return

        # File selection
        selected_file = st.selectbox(
            "Select FSM checkpoint file",
            options=fsm_files,
            format_func=lambda x: f"{x.name} ({datetime.fromtimestamp(x.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')})"
        )

        # Process button
        if st.button("Process File", type="primary"):
            st.session_state.current_file = selected_file
            st.session_state.processing = True

    # Main content area
    if 'current_file' in st.session_state and st.session_state.get('processing'):
        try:
            with st.spinner(f"Processing {st.session_state.current_file.name}..."):
                messages = process_fsm_file(st.session_state.current_file)
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
