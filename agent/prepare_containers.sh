SCRIPT_DIR=$(dirname "$0")
docker build -t botbuild/tsp_compiler -f ${SCRIPT_DIR}/Dockerfile.typespec ${SCRIPT_DIR}
docker build -t botbuild/app_schema -f ${SCRIPT_DIR}/Dockerfile.application ${SCRIPT_DIR}