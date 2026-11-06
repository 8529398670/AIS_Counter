#!/bin/sh
# Builds the helper for every OS and CPU into helper/dist/, where the server
# offers it for download (app/routes/ais_matlab.py). POSIX sh: the Dockerfile
# runs this too, on alpine. Run it from anywhere; it needs Go and nothing else.
set -eu
cd "$(dirname "$0")"
mkdir -p dist
for target in darwin-arm64 darwin-amd64 linux-amd64 linux-arm64 windows-amd64; do
  os=${target%-*}
  arch=${target#*-}
  suffix=""
  [ "$os" = windows ] && suffix=".exe"
  echo "building $target"
  CGO_ENABLED=0 GOOS=$os GOARCH=$arch go build -trimpath -ldflags "-s -w" -o "dist/ais-matlab-helper-$target$suffix" .
done
