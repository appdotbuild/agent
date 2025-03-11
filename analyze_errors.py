from langfuse import Langfuse
import pandas as pd
import joblib as jl
from tqdm import tqdm
from datetime import datetime
from pprint import pprint as _pprint
from copy import deepcopy
import re
from anthropic import AnthropicBedrock
from fire import Fire
from functools import reduce
from dataclasses import dataclass

langfuse = Langfuse()
memory = jl.Memory("/tmp/jl_cache", verbose=0)


def pprint(x):
    _pprint(x, width=160)


def get_antropic_response(prompt: str):
    client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    messages = [{"role": "user", "content": prompt}]

    response = client.messages.create(
        messages=messages,
        max_tokens=1024 * 16,
        model="anthropic.claude-3-5-haiku-20241022-v1:0",
        stream=False,
    )
    return response.content[0].text


@memory.cache
def get_traces(
    name: str = "create_bot", start_date: str | None = None, end_date: str | None = None, user_id: str | None = None
):
    kwargs = {"limit": 100, "name": name}
    if start_date:
        kwargs["from_timestamp"] = datetime.fromisoformat(start_date)
    if end_date:
        kwargs["to_timestamp"] = datetime.fromisoformat(end_date)
    if user_id:
        kwargs["user_id"] = user_id
    
    traces = langfuse.fetch_traces(**kwargs)
    traces_meta = traces.meta
    num_pages = traces_meta.total_pages

    all_traces = traces.data
    pool = jl.Parallel(n_jobs=-1, verbose=False, backend="threading")
    jobs = (
        jl.delayed(langfuse.fetch_traces)(page=i, **kwargs)
        for i in range(2, num_pages + 1)
    )

    for traces in pool(tqdm(jobs, total=num_pages - 1, desc="Fetching traces")):
        all_traces.extend(traces.data)

    full_traces_jobs = (
        jl.delayed(langfuse.fetch_trace)(trace.id) for trace in all_traces
    )

    pool = jl.Parallel(n_jobs=-1, verbose=False, backend="threading", batch_size=16)
    full_traces = pool(
        tqdm(full_traces_jobs, total=len(all_traces), desc="Fetching full traces")
    )
    return [x.data.dict() for x in full_traces]


def make_observation_tree(flat_list):
    id_map = {item["id"]: dict(item, children=[]) for item in flat_list}
    root_items = []

    for item in flat_list:
        current = id_map[item["id"]]
        parent_id = item.get("parentObservationId")

        if parent_id is None:
            # This is a root item
            root_items.append(current)
        else:
            parent = id_map.get(parent_id)
            if parent:
                parent["children"].append(current)

    def sort_tree(items):
        # Sort current level
        items.sort(key=lambda x: x.get("startTime", ""))
        # Recursively sort children
        for item in items:
            sort_tree(item["children"])
        return items

    return sort_tree(root_items)


def print_nested_structure(nested_list, depth=0, indent="--"):
    for item in nested_list:
        display_text = item.get("name", item.get("id", "Unknown"))
        print(f"{indent * depth}{display_text}")
        if item["children"]:
            print_nested_structure(item["children"], depth + 1, indent)


def flatten_tree(nested_list, flat_list=None):
    nested_list = deepcopy(nested_list)

    if flat_list is None:
        flat_list = []

    for item in nested_list:
        maybe_children = item.pop("children", [])
        flat_list.append(item)
        if maybe_children:
            flat_list = flatten_tree(maybe_children, flat_list)

    return flat_list


def _parse_tag(msg, tag="errors"):
    pattern = re.compile(f"<{tag}>(.*?)</{tag}>", re.DOTALL)
    match = pattern.search(msg)
    if match is None:
        return None
    return match.group(1).strip()


@dataclass
class ErrorInfo:
    error_message: str
    observation_id: str
    trace_data: dict


def _find_last_message(x):
    try:
        return x["input"][-1]["content"]
    except KeyError:
        return x["input"]["kwargs"]["messages"][-1]["content"]


def _extract_errors(data: list) -> list[ErrorInfo]:
    if len(data) <= 1:
        return []
    
    typespec_calls = [x for x in data if x["name"] == "Anthropic-generation"]
    error_calls = [x for x in typespec_calls if len(x["input"]) > 1]
    
    result = []
    for call in error_calls:
        error_message = _parse_tag(_find_last_message(call), "errors")
        if error_message:
            result.append(ErrorInfo(
                error_message=error_message,
                observation_id=call["id"],
                trace_data=call
            ))
    
    return result


def summarize(t: dict):
    t = t.copy()
    obs = t.pop("observations")

    try:
        prompt, bot_id = t["input"]["args"]
    except ValueError:
        (prompt,) = t["input"]["args"]
        bot_id = t["input"]["kwargs"].get("bot_id", "")

    if "tests" in (bot_id or ""):
        return

    created_at = t["createdAt"]
    cost = t["totalCost"]
    generation_calls = sum([1 for o in obs if o["name"] == "Anthropic-generation"])
    obs_tree = make_observation_tree(obs)
    trees = {x["name"]: x for x in obs_tree}
    gen_calls_per_type = {
        f"{name}_calls": sum(
            [
                1
                for y in [x["name"] for x in flatten_tree([trees[name]])]
                if y == "Anthropic-generation"
            ]
        )
        for name in trees
    }

    errors = {f"{k}_errors": _extract_errors(flatten_tree([trees[k]])) for k in trees}

    return {
        "prompt": prompt,
        "bot_id": bot_id,
        "created_at": created_at,
        "cost": cost,
        "generation_calls": generation_calls,
        **gen_calls_per_type,
        **errors,
        **t["metadata"],
        "trace_id": t["id"],
    }


def classify_error(x, taxonomy):
    if not x or pd.isna(x):
        return

    prompt = f""""
    Given the following error, classify it into one of the following categories:
        <taxonomy>
        {taxonomy}
        </taxonomy>

    Answer MUST BE a wrapped in <answer></answer> tags.

    <error>
    {x}
    </error>"""

    resp = get_antropic_response(prompt)
    return _parse_tag(resp, "answer")


def analyze_column(df: pd.DataFrame, col: str):
    vals = df[col].values
    errs = []
    
    # Collect unique errors
    for x in vals:
        if isinstance(x, list):  # This check is needed for None values
            for item in x:
                # Check if we already have this error message
                if not any(e.error_message == item.error_message for e in errs):
                    errs.append(item)
    
    print(f"Found {len(errs)} errors in {col}")

    if not errs:
        print(f"No errors found in {col}")
        return
        
    max_errs = 100
    max_prompt_size = 100000  # adjust based on model's context window
    
    # Adjust max_errs until prompt is within size limit
    while True:
        if len(errs) > max_errs:
            print(f"truncating {len(errs)} errors to {max_errs} ({len(errs) / max_errs:.1f}x)")
            errs_sample = errs[:max_errs]
        else:
            errs_sample = errs
            
        n_errors = len(errs_sample)
        err_texts = [e.error_message for e in errs_sample]
        
        prompt = f"""Given the list of errors, identify up to {min(n_errors // 2, 5)} common patterns and gives them short names. The errors are: {err_texts}.
        Please provide a short name for each pattern encompassing the names with <names>

        Example output:
            <names>
            MissingDependencyFile
            IncorrectStorageFormat
            InvalidTargetURL
            DeadlockWhileParsing
            InvalidUserInput
            </names>
        """
        
        if len(prompt) <= max_prompt_size or max_errs <= 25:
            break
            
        max_errs = max(5, max_errs // 2)
        print(f"prompt size: {len(prompt)}, reducing max_errs to {max_errs}")

    possible_errors = get_antropic_response(prompt)
    taxonomy = _parse_tag(possible_errors, "names").split("\n")

    jobs = (
        jl.delayed(classify_error)(err.error_message, taxonomy)
        for err in tqdm(errs, desc=f"classifying errors for {col}", disable=False)
    )

    pool = jl.Parallel(backend="threading", n_jobs=-1)
    classified_errors = pool(jobs)
    
    # Create lookup table for classifications
    lut = {}
    for err, cls in zip(errs, classified_errors):
        if cls:  # Only store if classification succeeded
            lut[err.error_message] = cls

    counter = {x: 0 for x in taxonomy}
    counter["unknown"] = 0

    # Classify all errors in the dataset
    result = []
    for sample in vals:
        if not isinstance(sample, list):
            result.append(None)
        else:
            classified_samples = []
            for err in sample:
                err_class = lut.get(err.error_message)
                
                if err_class:
                    # Create a new ErrorInfo with classification as the error message
                    classified_error = ErrorInfo(
                        error_message=err_class,
                        observation_id=err.observation_id,
                        trace_data=err.trace_data
                    )
                    classified_samples.append(classified_error)
                    
                    try:
                        counter[err_class] += 1
                    except KeyError:
                        counter["unknown"] += 1
            
            result.append(classified_samples if classified_samples else None)

    counter = {k: v for k, v in counter.items() if v > 0}

    print(col)
    print(counter)
    return result


def generate_error_analysis(df: pd.DataFrame):
    error_categories = [col for col in df.columns if col.endswith("_errors_classified")]
    error_analysis = {}
    
    for category in error_categories:
        if df[category].isna().all():
            continue

        all_errors = []
        for errors in df[category].dropna():
            if isinstance(errors, list):
                all_errors.extend([err.error_message for err in errors])

        if not all_errors:
            continue

        error_counts = {}
        error_examples = {}

        for error in set(all_errors):
            bots_with_error = df[
                df[category].apply(
                    lambda x: isinstance(x, list) and any(
                        err.error_message == error for err in x
                    )
                )
            ]
            
            examples = []
            for _, row in bots_with_error.iterrows():
                trace_id = row["trace_id"]
                
                obs_id = None
                if isinstance(row[category], list):
                    for err in row[category]:
                        if err.error_message == error:
                            obs_id = err.observation_id
                            break
                
                examples.append((trace_id, obs_id))
                
                if len(examples) >= 5:  # Limit to 5 examples
                    break
            
            error_counts[error] = all_errors.count(error)
            error_examples[error] = examples

        error_analysis[category] = {"counts": error_counts, "examples": error_examples}

    msg = "# Error Analysis\n"
    for category, data in error_analysis.items():
        msg += f"\n## {category}\n"
        for error, count in sorted(
            data["counts"].items(), key=lambda x: x[1], reverse=True
        ):
            msg += f"### {error}\n"
            msg += f"- **Occurrences:** {count}\n"
            links = []
            for trace_id, obs_id in data['examples'][error]:
                if obs_id:
                    link = f'[{trace_id}](https://cloud.langfuse.com/project/cm6j91sap009ux891llzvdjvi/traces/{trace_id}?observation={obs_id})'
                else:
                    link = f'[{trace_id}](https://cloud.langfuse.com/project/cm6j91sap009ux891llzvdjvi/traces/{trace_id})'
                links.append(link)
            msg += f"- **Example bots:** {', '.join(links)}\n"
            msg += "\n"

    with open("/tmp/error_analysis.md", "w") as f:
        f.write(msg)
    print(f"Error analysis saved to /tmp/error_analysis.md")


@memory.cache
def process_traces_and_classify(
    start_date: str | None = None,
    end_date: str | None = None,
    bot_name_pattern: str | None = None,
    user_id: str | None = None,
):
    traces = get_traces(start_date=start_date, end_date=end_date, user_id=user_id)
    pool = jl.Parallel(
        n_jobs=-1, backend="sequential", batch_size=1
    )  # no parallelization for now, maybe later?
    jobs = (jl.delayed(summarize)(t) for t in tqdm(traces, desc="Processing traces"))
    data = pool(jobs)
    df = pd.DataFrame(filter(None, data))
    if bot_name_pattern:
        df = df[df["bot_id"].fillna("").str.contains(bot_name_pattern)]
    err_cols = [x for x in df.columns if x.endswith("_errors")]
    for col in err_cols:
        classified_errors = analyze_column(df, col)
        if classified_errors is not None:
            df[f"{col}_classified"] = classified_errors
    return df


def convert_md_to_pdf():
    try:
        import subprocess
        print("Attempting to convert markdown to PDF...")
        subprocess.run(
            [
                "pandoc",
                "/tmp/error_analysis.md",
                "-o", "/tmp/error_analysis.pdf",
                "-V", "colorlinks=true",
                "-V", "linkcolor=blue",
            ],
            check=True,
            capture_output=True
        )
        print("PDF generated at /tmp/error_analysis.pdf")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Could not convert to PDF - pandoc may not be installed (brew install pandoc mactex)")
    except Exception as e:
        print(f"Unexpected error converting to PDF: {e}")


def main(
    start_date: str | None = None,
    end_date: str | None = None,
    bot_name_pattern: str | None = None,
    user_id: str | None = None,
):
    if start_date is None:
        start_date = (datetime.today() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    df = process_traces_and_classify(
        start_date=start_date, end_date=end_date, bot_name_pattern=bot_name_pattern, user_id=user_id
    )
    df.to_csv("/tmp/classified_errors.csv", index=False)
    print(f"Classified errors saved to /tmp/classified_errors.csv")
    generate_error_analysis(df)
    convert_md_to_pdf()


if __name__ == "__main__":
    Fire(main)

