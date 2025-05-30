import streamlit as st
from pathlib import Path
from typing import Dict, List, Any
import os
from analysis.utils import extract_trajectories_from_dump
from analysis.trace_loader import TraceLoader


def get_trace_patterns() -> List[str]:
    """Get the patterns for trace files to search."""
    patterns = []
    if st.sidebar.checkbox("FSM enter states", value=False):
        patterns.append("*fsm_enter.json")
    if st.sidebar.checkbox("FSM exit states", value=True):
        patterns.append("*fsm_exit.json")
    return patterns


def display_message(msg: Dict[str, Any], idx: int):
    """Display a single message in a nice format."""
    with st.expander(f"Message {idx + 1}: {msg.get('role', 'Unknown')}", expanded=False):
        content = msg.get("content", [""])
        if isinstance(content, list) and len(content) == 1:
            content = content[0]
        st.json(content)

        # Display additional fields
        excluded_fields = {"role", "content", "timestamp"}
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

        # storage type selection
        storage_type = st.radio("Storage Type", options=["Local", "S3"], help="Choose where to load traces from")

        if storage_type == "Local":
            current_dir = os.path.dirname(os.path.abspath(__file__))
            default_traces_dir = str(Path(os.path.join(current_dir, "../traces")))

            # local directory configuration
            local_dir = st.text_input(
                "Local Directory Path",
                value=os.environ.get("TRACES_DIR", default_traces_dir),
                help="Enter the path to the directory containing traces",
            )
            traces_location = Path(local_dir)
            if not traces_location.exists():
                st.error(f"Traces directory not found: {traces_location}")
                return
        else:
            # s3 bucket selection
            s3_bucket_options = ["staging-agent-service-snapshots", "prod-agent-service-snapshots", "custom"]

            selected_bucket = st.selectbox(
                "S3 Bucket",
                options=s3_bucket_options,
                help="Select a predefined bucket or choose 'custom' to enter your own",
            )

            if selected_bucket == "custom":
                s3_bucket = st.text_input(
                    "Custom S3 Bucket Name",
                    value=os.environ.get("SNAPSHOT_BUCKET", ""),
                    help="Enter the S3 bucket name containing traces",
                )
                if not s3_bucket:
                    st.warning("Please enter an S3 bucket name")
                    return
            else:
                s3_bucket = selected_bucket

            traces_location = s3_bucket

        # initialize trace loader
        trace_loader = TraceLoader(str(traces_location))

        if not trace_loader.is_available:
            st.error(f"Storage location not available: {traces_location}")
            return

        # get file patterns
        patterns = get_trace_patterns()
        if not patterns:
            st.warning("Please select at least one trace type")
            return

        # get list of files
        fsm_files = trace_loader.list_trace_files(patterns)

        if not fsm_files:
            st.warning("No FSM checkpoint files found")
            return

        # File selection
        def format_file_option(file_info):
            if file_info.get("is_local", True):
                name, *rest = file_info["name"].split("-")
                truncated = "-".join([name[:6] + "...", *rest])
                return f"{truncated} ({file_info['modified'].strftime('%Y-%m-%d %H:%M:%S')})"
            else:
                # for S3 files, show truncated trace ID + full filename
                path_parts = file_info["path"].split("/")
                if len(path_parts) > 1:
                    trace_id = path_parts[0]
                    filename = "/".join(path_parts[1:])
                    # truncate the trace ID (first two parts after - split)
                    id_parts = trace_id.split("-")
                    if len(id_parts) >= 2:
                        truncated_id = f"{id_parts[0][:6]}-{id_parts[1][:6]}..."
                    else:
                        truncated_id = trace_id[:12] + "..."
                    return f"{truncated_id}/{filename} ({file_info['modified'].strftime('%Y-%m-%d %H:%M:%S')})"
                else:
                    # fallback for files without directory
                    return f"{file_info['path']} ({file_info['modified'].strftime('%Y-%m-%d %H:%M:%S')})"

        selected_file = st.selectbox("Select FSM checkpoint file", options=fsm_files, format_func=format_file_option)

        actors_to_display = st.sidebar.multiselect(
            "Select Actors to Display",
            options=["Frontend", "Handler", "Draft", "Edit"],
            default=["Frontend", "Handler", "Draft", "Edit"],
        )
        # Process button
        if st.button("Process File", type="primary"):
            st.session_state.current_file = selected_file
            st.session_state.trace_loader = trace_loader
            st.session_state.processing = True

    # Main content area
    if "current_file" in st.session_state and st.session_state.get("processing"):
        try:
            with st.spinner(f"Processing {st.session_state.current_file['name']}..."):
                # load the file content
                trace_loader = st.session_state.trace_loader
                file_content = trace_loader.load_file(st.session_state.current_file)

                # extract trajectories from the loaded content
                messages = extract_trajectories_from_dump(file_content)
                st.session_state.messages = messages
                st.session_state.processing = False
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")
            st.session_state.processing = False

    # Display results
    if "messages" in st.session_state:
        messages = st.session_state.messages

        # Show full file path/name
        file_info = st.session_state.current_file
        if file_info.get("is_local", True):
            file_display = file_info["name"]
        else:
            file_display = file_info["path"]

        st.subheader(f"File: {file_display}")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Trajectories", len(messages))
        with col2:
            total_messages = sum(len(msgs) for msgs in messages.values())
            st.metric("Total Messages", total_messages)

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
                filtered_messages = [msg for msg in trajectory_messages if search_term.lower() in str(msg).lower()]
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
