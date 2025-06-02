import streamlit as st
from pathlib import Path
from typing import Dict, List, Any
import os
from analysis.utils import extract_trajectories_from_dump
from analysis.trace_loader import TraceLoader


def get_trace_pattern(file_type: str) -> str:
    """Get the pattern for trace files based on selected type."""
    patterns = {
        "FSM enter states": "*fsm_enter.json",
        "FSM exit states": "*fsm_exit.json", 
        "Top level agent": "*fsmtools_messages.json",
        "SSE events": "*sse*"
    }
    return patterns.get(file_type, "")


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


def display_top_level_message(msg: Dict[str, Any], idx: int):
    """Display a top-level agent message with better formatting for tool use."""
    role = msg.get('role', 'Unknown')
    
    # both user and assistant blocks collapsed by default
    expanded = False
    
    with st.expander(f"Message {idx + 1}: {role.upper()}", expanded=expanded):
        content = msg.get("content", [])
        
        if isinstance(content, list):
            for i, item in enumerate(content):
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        st.markdown(f"**Text:**")
                        text_content = item.get("text", "")
                        # use markdown for assistant messages, plain text for others
                        if role == "assistant":
                            st.markdown(text_content)
                        else:
                            st.text(text_content)
                    
                    elif item.get("type") == "tool_use":
                        st.markdown("**🔧 Tool Use:**")
                        col1, col2 = st.columns([1, 3])
                        with col1:
                            st.code(item.get("name", "Unknown"))
                        with col2:
                            st.json(item.get("input", {}))
                    
                    elif item.get("type") == "tool_use_result":
                        st.markdown("**✅ Tool Result:**")
                        tool_use = item.get("tool_use", {})
                        tool_result = item.get("tool_result", {})
                        
                        # show tool info
                        st.markdown(f"*Tool:* `{tool_use.get('name', 'Unknown')}`")
                        
                        # show tool result content
                        if "content" in tool_result:
                            try:
                                # try to parse JSON content if it's a string
                                import json
                                result_content = tool_result["content"]
                                if isinstance(result_content, str):
                                    try:
                                        result_content = json.loads(result_content)
                                    except:
                                        pass
                                
                                # display the content
                                with st.container():
                                    st.json(result_content)
                            except:
                                st.text(tool_result["content"])
                    
                    else:
                        # fallback for unknown types
                        st.json(item)
                
                # add separator between content items
                if i < len(content) - 1:
                    st.divider()
        else:
            # fallback for non-list content
            st.json(content)


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

        # file type selection
        file_type = st.radio(
            "Trace Type",
            options=["FSM exit states", "FSM enter states", "Top level agent", "SSE events"],
            help="Select the type of trace files to analyze"
        )

        # get file pattern
        pattern = get_trace_pattern(file_type)
        if not pattern:
            st.warning("Invalid trace type selected")
            return

        # get list of files
        fsm_files = trace_loader.list_trace_files([pattern])

        if not fsm_files:
            st.warning(f"No {file_type} files found")
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

        selected_file = st.selectbox("Select file", options=fsm_files, format_func=format_file_option)

        # actors selection - only show for FSM enter/exit files
        if file_type in ["FSM exit states", "FSM enter states"]:
            actors_to_display = st.sidebar.multiselect(
                "Select Actors to Display",
                options=["Frontend", "Handler", "Draft", "Edit"],
                default=["Frontend", "Handler", "Draft", "Edit"],
            )
        else:
            actors_to_display = []
        # Process button
        if st.button("Process File", type="primary"):
            st.session_state.current_file = selected_file
            st.session_state.trace_loader = trace_loader
            st.session_state.actors_to_display = actors_to_display
            st.session_state.processing = True

    # Main content area
    if "current_file" in st.session_state and st.session_state.get("processing"):
        try:
            with st.spinner(f"Processing {st.session_state.current_file['name']}..."):
                # load the file content
                trace_loader = st.session_state.trace_loader
                file_content = trace_loader.load_file(st.session_state.current_file)
                
                # determine trace type based on filename
                filename = st.session_state.current_file["name"]
                
                if "fsm_enter" in filename or "fsm_exit" in filename:
                    # FSM traces - use the existing extraction logic
                    messages = extract_trajectories_from_dump(file_content)
                    st.session_state.messages = messages
                    st.session_state.trace_type = "fsm"
                elif "fsmtools_messages" in filename:
                    # top-level agent messages - store as special type
                    st.session_state.raw_content = file_content
                    st.session_state.trace_type = "fsmtools"
                else:
                    # other traces (sse_events, etc.) - store raw content
                    st.session_state.raw_content = file_content
                    st.session_state.trace_type = "raw"
                
                st.session_state.processing = False
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")
            st.session_state.processing = False

    # Display results
    if "trace_type" in st.session_state:
        # Show full file path/name
        file_info = st.session_state.current_file
        if file_info.get("is_local", True):
            file_display = file_info["name"]
        else:
            file_display = file_info["path"]

        st.subheader(f"File: {file_display}")

        if st.session_state.trace_type == "fsm" and "messages" in st.session_state:
            # FSM trace display logic
            messages = st.session_state.messages

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
            actors_to_display = st.session_state.get("actors_to_display", [])
            for trajectory_name, trajectory_messages in messages.items():
                # if actors filter is specified, check if trajectory matches
                if actors_to_display:
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

        elif st.session_state.trace_type == "fsmtools" and "raw_content" in st.session_state:
            # FSMTools messages display logic
            st.header("Top-Level Agent Messages")
            
            # parse the messages
            messages = st.session_state.raw_content
            if isinstance(messages, list):
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Total Messages", len(messages))
                with col2:
                    # count tool uses
                    tool_uses = sum(
                        1 for msg in messages 
                        if isinstance(msg.get("content"), list) 
                        for item in msg["content"] 
                        if isinstance(item, dict) and item.get("type") == "tool_use"
                    )
                    st.metric("Tool Uses", tool_uses)
                
                # search box
                search_term = st.text_input("Search in messages", placeholder="Enter search term...")
                
                # display messages
                for idx, msg in enumerate(messages):
                    # filter if search term is provided
                    if search_term and search_term.lower() not in str(msg).lower():
                        continue
                    
                    display_top_level_message(msg, idx)
            else:
                st.error("Invalid message format")
        
        elif st.session_state.trace_type == "raw" and "raw_content" in st.session_state:
            # Raw trace display logic - show plain JSON
            st.header("Raw Trace Data")
            
            # Display the raw JSON content
            with st.expander("Full JSON Content", expanded=True):
                st.json(st.session_state.raw_content)

    else:
        st.info("👈 Select an FSM checkpoint file from the sidebar to begin analysis")


if __name__ == "__main__":
    main()
