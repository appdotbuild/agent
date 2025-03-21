import anyio
from run_cli import run_agent

def main():
    export_dir = input("Where to place generated app: ")
    anyio.run(run_agent, export_dir)


if __name__ == "__main__":
    main()
