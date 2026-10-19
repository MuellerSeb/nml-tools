#!/bin/sh
cd -- "$(dirname -- "$0")" || exit 1
mkdir -p out
exec nml-tools gui -i ./ -o ./out
