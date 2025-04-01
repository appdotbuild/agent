#!/bin/bash

# Install TypeSpec compiler if not already installed
if ! command -v tsp &> /dev/null; then
    echo "Installing TypeSpec compiler..."
    npm install -g @typespec/compiler
fi

# Install local dependencies
npm install

# Compile TypeSpec to OpenAPI 3.0
npx tsp compile agent_api.tsp

echo "TypeSpec compilation complete. Generated files:"
ls -la *.yaml