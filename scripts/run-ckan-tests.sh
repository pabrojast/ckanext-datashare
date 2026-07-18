#!/usr/bin/env bash
#
# ckanext-datashare -- reproducible CKAN 2.10 verification driver.
#
# Builds Dockerfile.test (real CKAN 2.10 + the plugin) and runs:
#   1. a plugin-LOAD smoke check (DatasharePlugin registries non-empty),
#   2. the full pytest suite (policy matrix + grant DB behavior + scaffold).
#
# Usage (from the repo root, requires Docker):
#   bash scripts/run-ckan-tests.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

IMAGE="datashare-test"

echo "== ckanext-datashare: CKAN 2.10 verification harness =="

echo "-- docker build -f Dockerfile.test -t ${IMAGE} ."
docker build -f Dockerfile.test -t "${IMAGE}" .

echo "-- plugin-load smoke check (DatasharePlugin hooks)"
docker run --rm -i "${IMAGE}" python - <<'PY'
import sys

from ckanext.datashare.plugin import DatasharePlugin

plugin = DatasharePlugin()
checks = {
    'actions': plugin.get_actions(),
    'auth': plugin.get_auth_functions(),
    'validators': plugin.get_validators(),
    'helpers': plugin.get_helpers(),
    'commands': plugin.get_commands(),
}
for name, registry in checks.items():
    if not registry:
        print('FAIL: empty registry: %s' % name)
        sys.exit(1)
print('PLUGIN OK: %s' % {k: len(v) for k, v in checks.items()})
PY

echo "-- pytest suite"
docker run --rm "${IMAGE}" \
    pytest -p no:ckan -q /plugin/ckanext/datashare/tests

echo "== PASS: all verification layers green =="
