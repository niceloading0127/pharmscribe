#!/usr/bin/env bash
# List the videos in a YouTube playlist/course as: index<TAB>id<TAB>title
# Usage: playlist.sh <playlist_url>
set -euo pipefail
URL="${1:?Usage: playlist.sh <playlist_url>}"
command -v yt-dlp >/dev/null || { echo "ERROR: yt-dlp not found. Install with 'pip install yt-dlp'."; exit 1; }
yt-dlp --flat-playlist --print "%(playlist_index)s	%(id)s	%(title)s" "$URL"
