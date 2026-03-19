#!/bin/bash

echo "[POC] appdotbuild namespace is controlled by security researcher"

echo "[POC] Executed on: $(whoami)@$(hostname)"

# harmless proof file
touch /tmp/appdotbuild_poc

echo "[POC] Created /tmp/appdotbuild_poc"
