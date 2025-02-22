from turtledemo.chaos import N
from langfuse import Langfuse
import pandas as pd
import joblib as jl
from tqdm import cli, tqdm
import numpy as np
import json
from datetime import datetime
from pprint import pprint as _pprint
from collections import Counter
from copy import deepcopy
import re
from anthropic import AnthropicBedrock
from functools import reduce

langfuse = Langfuse()
memory = jl.Memory("/tmp/jl_cache", verbose=0)


def pprint(x):
    _pprint(x, width=160)


def get_antropic_response(prompt: str):
    client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    messages = [{"role": "user", "content": prompt}]
    response = client.messages.create(
        messages=messages,
        max_tokens=8192,
        model="anthropic.claude-3-5-haiku-20241022-v1:0",
        stream=False,
    )
    return response.content[0].text


# todo: add date range filter
@memory.cache
def get_traces():
    traces = langfuse.fetch_traces(limit=100, name="create_bot")
    traces_meta = traces.meta
    num_pages = traces_meta.total_pages

    all_traces = traces.data
    pool = jl.Parallel(n_jobs=-1, verbose=False, backend="threading")
    jobs = (
        jl.delayed(langfuse.fetch_traces)(page=i, limit=100, name="create_bot")
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


def _extract_errors(data: list) -> list:
    if len(data) <= 1:
        return []
    typespec_calls = [x for x in data if x["name"] == "Anthropic-generation"]
    error_calls = [x for x in typespec_calls if len(x["input"]) > 1]

    def _find_last_message(x):
        try:
            return x["input"][-1]["content"]
        except KeyError:
            return x["input"]["kwargs"]["messages"][-1]["content"]

    errors = [
        _parse_tag(_find_last_message(x), "errors")
        for x in error_calls
        if len(x["input"])
    ]
    return [x for x in errors if x]


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
    # FixMe: ignoring old data
    if not created_at.startswith("2025-02-"):
        return
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
    errs = reduce(lambda x, y: x + y, [x for x in vals if isinstance(x, list)] + [[]])
    errs = list(set(errs))

    if not errs:
        print(f"No errors found in {col}")
        return

    prompt = f"""Given the list of errors, identify up to 5 common patterns and gives them short names. The errors are: {errs}.
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

    possible_errors = get_antropic_response(prompt)
    taxonomy = _parse_tag(possible_errors, "names").split("\n")

    jobs = (
        jl.delayed(classify_error)(err, taxonomy)
        for err in tqdm(errs, desc=f"classifying errors for {col}", disable=False)
    )

    pool = jl.Parallel(backend="threading", n_jobs=-1)
    classified_errors = pool(jobs)
    lut = {x: y for x, y in zip(errs, classified_errors)}

    counter = {x: 0 for x in taxonomy}
    counter["unknown"] = 0

    result = []
    for sample in vals:
        if not isinstance(sample, list):
            result.append(None)
        else:
            err_classes = [lut[err] for err in sample]
            result.append(err_classes)
            for err_class in err_classes:
                try:
                    counter[err_class] += 1
                except KeyError:
                    # means we can't extract <answer>
                    counter["unknown"] += 1

    if counter["unknown"] == 0:
        counter.pop("unknown")

    print(col)
    print(counter)
    return result


def main():
    traces = get_traces()
    pool = jl.Parallel(
        n_jobs=-1, backend="sequential", batch_size=1
    )  # no parallelization for now, maybe later?
    jobs = (jl.delayed(summarize)(t) for t in tqdm(traces, desc="Processing traces"))
    data = pool(jobs)
    df = pd.DataFrame(filter(None, data))
    err_cols = [x for x in df.columns if x.endswith("_errors")]
    for col in err_cols:
        classified_errors = analyze_column(df, col)
        if classified_errors is not None:
            df[f"{col}_classified"] = classified_errors

    df.to_csv("/tmp/classified_errors.csv", index=False)


if __name__ == "__main__":
    main()
