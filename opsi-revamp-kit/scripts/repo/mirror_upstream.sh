#!/usr/bin/env bash
# Keep a PRIVATE enterprise mirror of a public upstream repository (branches + tags only).
#
# Why a mirror and not a GitHub fork: forks of public repositories are always public and their
# visibility cannot be changed (GitHub docs), and GitHub Enterprise Server cannot fork github.com repos.
# A private mirror gives availability, scanning and provenance without exposing anything.
#
#   scripts/repo/mirror_upstream.sh https://github.com/open-metadata/OpenMetadata.git \
#       https://git.corp.example/upstream-mirrors/OpenMetadata.git [cache_dir]
#   MIRROR_BRANCHES="main release-*" scripts/repo/mirror_upstream.sh ...   # limit branches (big repos)
#
# Rules: the mirror repo is written ONLY by this job (service account); humans never push to it;
# nobody commits product code to it. Authentication via the credential helper of the job runner -
# never credentials in the URLs (refused below).
# Only refs/heads/* and refs/tags/* are pushed: GitHub exposes read-only refs/pull/* that a
# `git push --mirror` from a full mirror clone would try (and fail) to push.
set -euo pipefail
UPSTREAM="${1:?upstream URL}"; MIRROR="${2:?enterprise mirror URL}"
CACHE="${3:-${MIRROR_CACHE:-$HOME/.cache/opsi-mirrors}}"
BRANCHES="${MIRROR_BRANCHES:-*}"
for u in "$UPSTREAM" "$MIRROR"; do
  [[ "$u" =~ ://[^/@]+@ ]] && { echo "refusing: credentials embedded in URL" >&2; exit 2; }
done
DIR="$CACHE/$(basename "${UPSTREAM%.git}").git"
mkdir -p "$CACHE"
[[ -d "$DIR" ]] || git clone --bare --quiet "$UPSTREAM" "$DIR"
git -C "$DIR" remote set-url origin "$UPSTREAM"
FETCH=(); PUSH=()
set -f   # branch patterns like * or release-* are git refspec globs, not filename globs
for b in $BRANCHES; do FETCH+=("+refs/heads/$b:refs/heads/$b"); PUSH+=("+refs/heads/$b:refs/heads/$b"); done
set +f
git -C "$DIR" fetch --prune --quiet origin "${FETCH[@]}" '+refs/tags/*:refs/tags/*'
git -C "$DIR" push --prune --quiet "$MIRROR" "${PUSH[@]}" '+refs/tags/*:refs/tags/*'
echo "$(date -u +%FT%TZ) mirrored $UPSTREAM -> $MIRROR ($(git -C "$DIR" for-each-ref refs/tags | wc -l) tags)"
