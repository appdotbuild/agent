import anyio
from run_cli import run_agent

def main():
    export_dir = input("Output directory: ")
    anyio.run(run_agent, export_dir)


if __name__ == "__main__":
    main()
