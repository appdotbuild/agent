import anyio
import argparse
from run_cli import run_agent

def main():
    parser = argparse.ArgumentParser(
        description="Run agent for generating fullstack app."
    )
    parser.add_argument(
        "--num_beams",
        type=int,
        default=1,
        help="Number of parallel searches to run."
    )
    parser.add_argument(
        "--export_dir",
        type=str,
        help="Directory where the generated app will be placed."
    )
    args = parser.parse_args()
    if args.num_beams < 1:
        raise argparse.ArgumentTypeError("num_beams must be at least 1")
    export_dir = args.export_dir or input("Where to place generated app: ")
    anyio.run(run_agent, export_dir, args.num_beams)


if __name__ == "__main__":
    main()
