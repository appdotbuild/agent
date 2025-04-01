#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd "${SCRIPT_DIR}/../../" && pwd)"

mkdir -p "${SCRIPT_DIR}/.generated"

TMP_DIR=$(mktemp -d)
echo "Created temporary directory: ${TMP_DIR}"

cp "${SCRIPT_DIR}/agent_api.tsp" "${TMP_DIR}/main.tsp"

cat > "${TMP_DIR}/helpers.js" << EOL
// Empty helpers file
EOL

# Create tspconfig.yaml with OpenAPI3 emitter
cat > "${TMP_DIR}/tspconfig.yaml" << EOL
emit:
  - "@typespec/openapi3"
options:
  "@typespec/openapi3":
    output-file: "openapi.yaml"
EOL

echo "Compiling TypeSpec to OpenAPI..."
docker run --rm -v "${TMP_DIR}:/app" botbuild/tsp_compiler tsp compile . --emit @typespec/openapi3

# Check if the OpenAPI spec was generated
if [ -f "${TMP_DIR}/openapi.yaml" ]; then
    # Copy the generated spec to the .generated directory
    cp "${TMP_DIR}/openapi.yaml" "${SCRIPT_DIR}/.generated/openapi.yaml"
    echo "OpenAPI spec successfully generated at: ${SCRIPT_DIR}/.generated/openapi.yaml"
else
    echo "Error: OpenAPI spec was not generated"
    # Print container directory contents for debugging
    docker run --rm -v "${TMP_DIR}:/app" botbuild/tsp_compiler ls -la
    exit 1
fi

rm -rf "${TMP_DIR}"
echo "Cleaned up temporary directory"

echo "OpenAPI generation completed successfully!"