#!/bin/sh
# =============================================================================
# engine-update.sh — seed the simc-engine volume from the official SimC
# Docker nightly image.
#
# Runs INSIDE the simulationcraftorg/simc nightly image (Alpine, busybox sh)
# as a one-shot compose service. Extracts the prebuilt engine binary, the
# profiles tree, and the full musl runtime (loader + shared libs the binary
# links against) into the shared simc-engine volume, then writes a small
# wrapper script that the worker invokes as the engine.
#
# The musl runtime is copied because the nightly binary is musl-linked and
# Alpine-built; the worker image (Debian/glibc) cannot provide compatible
# copies of those libraries, so we ship the exact ones from the nightly image.
#
# Env:
#   NIGHTLY_TAG   Tag of the nightly image being extracted (idempotency marker)
#   DEST          Write target inside the mounted volume (default: /volume/simc-nightly)
#   ENGINE_HOME   The same directory as seen from INSIDE the worker container
#                 (default: /app/thirdparties/simc-nightly) — baked into the
#                 wrapper because the volume is mounted at different points in
#                 the engine-update (/volume) and worker (/app/thirdparties)
#                 containers.
# =============================================================================
set -eu

SRC=/app/SimulationCraft
DEST="${DEST:-/volume/simc-nightly}"
ENGINE_HOME="${ENGINE_HOME:-/app/thirdparties/simc-nightly}"
TAG="${NIGHTLY_TAG:-unknown}"

if [ ! -x "$SRC/simc" ]; then
    echo "engine-update: $SRC/simc not found — wrong source image?" >&2
    exit 1
fi

if [ -f "$DEST/.nightly_tag" ] && [ "$(cat "$DEST/.nightly_tag")" = "$TAG" ]; then
    echo "engine-update: engine $TAG already extracted at $DEST — nothing to do."
    exit 0
fi

echo "engine-update: extracting SimC nightly $TAG into $DEST ..."
mkdir -p "$DEST/lib"

cp "$SRC/simc" "$DEST/simc.bin"
[ -d "$DEST/profiles" ] && rm -rf "$DEST/profiles"
[ -d "$SRC/profiles" ] && cp -r "$SRC/profiles" "$DEST/profiles"

# Musl dynamic loader plus every shared library the binary resolves to.
cp -L /lib/ld-musl-x86_64.so.1 "$DEST/lib/"
ldd "$SRC/simc" | awk '/=> \// {print $3}' | while read -r lib; do
    cp -L "$lib" "$DEST/lib/" 2>/dev/null || true
done

# Wrapper the worker calls as the engine. Invokes the copied musl loader
# directly with the copied library path, so nothing from the nightly image's
# base OS is required at runtime. Paths are absolute (ENGINE_HOME) because the
# volume is always mounted at the same point inside the worker container.
LOADER="$ENGINE_HOME/lib/ld-musl-x86_64.so.1"
# Unquoted heredoc: $ENGINE_HOME/$LOADER expand now; \$@ stays literal.
cat > "$DEST/simc" <<WRAP
#!/bin/sh
exec "$LOADER" --library-path "$ENGINE_HOME/lib" "$ENGINE_HOME/simc.bin" "\$@"
WRAP

chmod -R a+rX "$DEST"
chmod +x "$DEST/simc" "$DEST/simc.bin" "$DEST/lib/ld-musl-x86_64.so.1"
# The worker container runs as uid/gid 1000 (appuser); hand it ownership when
# this script runs as root (the compose service default).
chown -R 1000:1000 "$DEST" 2>/dev/null || true

echo "$TAG" > "$DEST/.nightly_tag"
echo "engine-update: done. Engine wrapper: $DEST/simc"
# Smoke-test the extracted engine through the copied loader (the same command
# the worker's wrapper will run). A missing input file is expected to fail;
# what matters is that the binary starts and prints its version banner.
"$DEST/lib/ld-musl-x86_64.so.1" --library-path "$DEST/lib" "$DEST/simc.bin" /nonexistent.simc 2>&1 | head -1 || true
