import os
import uvicorn


def start_app() -> None:
    uvicorn.run(
        "app:app",
        host=os.getenv("HOST"),
        port=int(os.getenv("PORT")),
        access_log=False,
    )


if __name__ == "__main__":
    start_app()
