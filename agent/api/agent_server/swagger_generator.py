import shlex
import os
import sys
from typing import TypedDict
import docker
from docker.errors import APIError
import docker.models.containers
from logging import getLogger

logger = getLogger(__name__) 

class CompileResult(TypedDict):
    openapi_spec: str | None
    error: str | None

class OpenApiGenerator:
    """
    Handles the generation of OpenAPI specifications from TypeSpec files
    using a dedicated Docker container. Ultra-simplified version.
    """
    def __init__(self, tsp_image: str):
        self.tsp_image = tsp_image
        self.client = docker.from_env()
        
    @staticmethod
    def _exec(container: docker.models.containers.Container, command: list[str] | str, workdir: str | None = None):
        """Basic exec_run wrapper, raises exception on failure."""
        exit_code, output = container.exec_run(command, workdir=workdir, demux=False)
        if exit_code != 0:
            output_str = output.decode('utf-8', errors='replace') if output else "No output"
            cmd_str = command if isinstance(command, str) else ' '.join(command)
            raise RuntimeError(f"Command failed (Exit Code: {exit_code}): {cmd_str}\nOutput:\n{output_str}")
        return output

    def generate_openapi(self, tsp_file_path: str) -> CompileResult:
        """
        Generates OpenAPI spec. Minimal checks, assumes success path.
        """
        container = None
        try:
            abs_tsp_file_path = os.path.abspath(tsp_file_path)
            if not os.path.isfile(abs_tsp_file_path):
                 raise FileNotFoundError(f"Input file not found: {abs_tsp_file_path}")
            with open(abs_tsp_file_path, 'r', encoding='utf-8') as f:
                schema_content = f.read()

            container = self.client.containers.run(
                self.tsp_image,
                command=["sleep", "60"],
                detach=True,
                working_dir="/app",
                remove=True
            )

            schema_container_path = "schema.tsp"
            quoted_schema = shlex.quote(schema_content)
            copy_command = f"echo {quoted_schema} > {schema_container_path}"
            self._exec(container, ["sh", "-c", copy_command], workdir="/app")

            openapi_container_path = "/app/tsp-output/agent_api.yaml"
            compile_command = [
                "tsp", "compile", schema_container_path,
                "--emit", "@typespec/openapi3",
                "--output-path", "."
            ]
            self._exec(container, compile_command, workdir="/app")

            read_command = ["cat", openapi_container_path]
            openapi_bytes = self._exec(container, read_command, workdir="/")
            openapi_spec = openapi_bytes.decode("utf-8", errors="replace")

            return CompileResult(openapi_spec=openapi_spec, error=None)

        except Exception as e:
            logger.error(f"OpenAPI generation failed: {e}", exc_info=True) 
            error_msg = str(e)
            if isinstance(e, FileNotFoundError):
                 error_msg = f"Input file not found: {tsp_file_path}"
            return CompileResult(openapi_spec=None, error=error_msg)

        finally:
             if container:
                 try:
                     container.remove(force=True)
                 except APIError as e:
                      logger.warning(f"Failed to remove container {container.id}: {e}")

if __name__ == "__main__":
    DEFAULT_TSP_IMAGE = "botbuild/tsp_compiler"

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, "..", "..", ".."))
    DEFAULT_TSP_FILE_REL = "agent/api/agent_server/agent_api.tsp"
    DEFAULT_TSP_FILE_ABS = os.path.join(project_root, DEFAULT_TSP_FILE_REL)

    OUTPUT_DIR_REL = ".generated"
    OUTPUT_DIR_ABS = os.path.join(script_dir, OUTPUT_DIR_REL)
    DEFAULT_OUTPUT_FILE_ABS = os.path.join(OUTPUT_DIR_ABS, "agent_api.yaml")

    print(f"Generating OpenAPI spec:")
    print(f"  Input: {DEFAULT_TSP_FILE_ABS}")
    print(f"  Output: {DEFAULT_OUTPUT_FILE_ABS}")

    generator = OpenApiGenerator(tsp_image=DEFAULT_TSP_IMAGE)
    result = generator.generate_openapi(tsp_file_path=DEFAULT_TSP_FILE_ABS)
    if result["error"]:
        print(f"\nERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if result["openapi_spec"]:
        os.makedirs(OUTPUT_DIR_ABS, exist_ok=True)
        
        with open(DEFAULT_OUTPUT_FILE_ABS, "w", encoding="utf-8") as f:
            f.write(result["openapi_spec"])
        print(f"Successfully generated and saved spec to: {DEFAULT_OUTPUT_FILE_ABS}")
        sys.exit(0)
    else:
        print("\nERROR: Generation finished with no spec and no error.", file=sys.stderr)
        sys.exit(1)
