#!/usr/bin/env bash
# Scan the built final image without exposing Docker's socket or registry creds
# to the scanner. Full results retain unfixed findings; only fixable HIGH/CRITICAL
# findings fail the gate. Scanner errors fail closed under `set -e`.
set -euo pipefail

image=${1:?Usage: bash scripts/scan-runtime-image.sh IMAGE OUTPUT_DIR [CACHE_DIR]}
output=${2:?An output directory is required}
cache=${3:-"$output/cache"}
scanner=aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c

mkdir -p "$output" "$cache"
output=$(realpath "$output")
cache=$(realpath "$cache")
archive="$output/image.tar"
trap 'rm -f "$archive"' EXIT

docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' "$image" > "$output/image.txt"
docker image save --output "$archive" "$image"
db_flags=()
if [[ ${TRIVY_SKIP_DB_UPDATE:-false} == true ]]; then
    db_flags+=(--skip-db-update)
fi
docker run --rm \
    -v "$output:/reports" -v "$cache:/cache" \
    "$scanner" image --config '' --ignorefile '' \
    --cache-dir /cache --scanners vuln --timeout 10m \
    "${db_flags[@]}" --format json --output /reports/scan.json \
    --input /reports/image.tar
docker run --rm --network none -v "$cache:/cache:ro" \
    "$scanner" --cache-dir /cache --version > "$output/scanner.txt"
sha256sum "$cache/db/trivy.db" > "$output/database-sha256.txt"

# Treat missing/malformed scan results as an execution failure, not a clean scan.
jq -e '.SchemaVersion and (.Results | type == "array")' "$output/scan.json" > /dev/null
jq '[.Results[].Vulnerabilities[]?] | group_by(.Severity) |
    map({severity: .[0].Severity, count: length})' "$output/scan.json" > "$output/summary.json"
jq '[.Results[] as $r | $r.Vulnerabilities[]? |
    select(.Severity == "HIGH" or .Severity == "CRITICAL") |
    {id: .VulnerabilityID, package: .PkgName, path: .PkgPath, type: $r.Type,
     installed: .InstalledVersion, fixed: .FixedVersion, status: .Status,
     severity: .Severity, severity_source: .SeveritySource, source: .DataSource.ID}]' \
    "$output/scan.json" > "$output/high-critical.json"
jq '[.[] | select(.fixed != null and .fixed != "")]' \
    "$output/high-critical.json" > "$output/fixable-high-critical.json"
jq -e 'length == 0' "$output/fixable-high-critical.json"
