#!/bin/bash
# Stops the hourly refresh. Your tab history (db.json, data.js, thumbs) is left in this folder.
PLIST="$HOME/Library/LaunchAgents/com.tabtracker.refresh.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "Hourly refresh removed. Delete this folder too if you want your tab history gone."
