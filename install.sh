#!/bin/bash
# Installs the hourly refresh for Tab Tracker (macOS + Google Chrome).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.tabtracker.refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "$HERE" in
  "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*)
    echo "Tab Tracker is in $HERE."
    echo "macOS blocks background jobs from Documents, Desktop and Downloads, so the hourly refresh would fail."
    echo "Move this folder somewhere like ~/TabTracker and run install.sh again."
    exit 1 ;;
esac

[ -d "/Applications/Google Chrome.app" ] || { echo "Google Chrome wasn't found in /Applications."; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>-I</string><string>$HERE/tabtracker.py</string></array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$HERE/tabtracker.log</string>
  <key>StandardErrorPath</key><string>$HERE/tabtracker.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed. Tab Tracker will refresh every hour while Chrome is open."
echo
echo "macOS will ask whether python3 may control Google Chrome. Click Allow."
echo "Then open $HERE/index.html in Chrome and bookmark it."
