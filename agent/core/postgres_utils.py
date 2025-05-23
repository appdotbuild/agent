import uuid
import dagger
from dagger import dag
from core.dagger_utils import ExecResult

def create_postgres_service():
    """Create a PostgreSQL service with unique instance ID."""
    return (
        dag.container()
        .from_("postgres:17.0-alpine")
        .with_env_variable("POSTGRES_USER", "postgres")
        .with_env_variable("POSTGRES_PASSWORD", "postgres")
        .with_env_variable("POSTGRES_DB", "postgres")
        .with_env_variable("INSTANCE_ID", uuid.uuid4().hex)
        .as_service(use_entrypoint=True)
    )

def pg_health_check_cmd(timeout: int = 30):
    return [
        "sh", "-c",
        f"for i in $(seq 1 {timeout}); do "
        "pg_isready -h postgres -U postgres && exit 0; "
        "echo 'Waiting for PostgreSQL...' && sleep 1; "
        "done; exit 1"
    ]

async def drizzle_push(ctr: dagger.Container, postgresdb: dagger.Service | None) -> ExecResult:
    """Run drizzle-kit push with postgres service."""

    if postgresdb is None:
        postgresdb = create_postgres_service()

    push_ctr = (
        ctr
        .with_exec(["apk", "--update", "add", "postgresql-client"])
        .with_service_binding("postgres", postgresdb)
        .with_env_variable("APP_DATABASE_URL", "postgres://postgres:postgres@postgres:5432/postgres")
        .with_exec(pg_health_check_cmd())
        .with_workdir("server")
        .with_exec(["bun", "run", "drizzle-kit", "push", "--force"])
    )
    result = await ExecResult.from_ctr(push_ctr)
    return result
