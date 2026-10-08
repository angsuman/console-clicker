#!/usr/bin/env bash
set -euo pipefail

app=/opt/ConsoleClicker/ConsoleClicker
test_directory=/tmp/clicker-docker-test
export XDG_CONFIG_HOME="$test_directory/config"
export DISPLAY=:99
export XDG_SESSION_TYPE=x11
mkdir -p "$XDG_CONFIG_HOME"
printf 'session.screen0.rootCommand: true\n' > "$test_directory/fluxbox-init"

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        if xdpyinfo >/dev/null 2>&1; then
            import -window root /tmp/clicker-failure.png || true
            "$app" --check-image /tmp/clicker-failure.png || true
        fi
        for log in /tmp/clicker-app.log /tmp/clicker-demo.log "$XDG_CONFIG_HOME/console-clicker/approvals.log"; do
            if [ -f "$log" ]; then cat "$log"; fi
        done
    fi
    jobs -pr | xargs -r kill || true
    exit "$status"
}
trap cleanup EXIT

for command in python python3 tesseract; do
    if command -v "$command"; then
        echo "Unexpected system runtime: $command" >&2
        exit 1
    fi
done

echo 'Checking bundled OCR: positive and negative fixtures'
for fixture in approval approval_boxed opencode_once; do
    "$app" --check-image "/opt/fixtures/$fixture.png"
done
for fixture in opencode_always opencode_reject; do
    status=0
    "$app" --check-image "/opt/fixtures/$fixture.png" || status=$?
    test "$status" -eq 2
done

Xvfb "$DISPLAY" -screen 0 2200x1000x24 -nolisten tcp >/tmp/clicker-xvfb.log 2>&1 &
for attempt in {1..50}; do
    if xdpyinfo >/dev/null 2>&1; then break; fi
    sleep 0.1
done
xdpyinfo >/dev/null
fluxbox -rc "$test_directory/fluxbox-init" >/tmp/clicker-fluxbox.log 2>&1 &
"$app" >/tmp/clicker-app.log 2>&1 &
app_pid=$!
"$app" --demo >/tmp/clicker-demo.log 2>&1 &
demo_pid=$!

find_window() {
    for attempt in {1..50}; do
        if window=$(xdotool search --onlyvisible --name "$1" 2>/dev/null | head -n 1); then
            if [ -n "$window" ]; then echo "$window"; return; fi
        fi
        sleep 0.2
    done
    echo "Window did not appear: $1" >&2
    return 1
}
app_window=$(find_window '^Console Clicker$')
demo_window=$(find_window '^Clicker demo terminal$')
xdotool windowmove "$app_window" 0 40
xdotool windowmove "$demo_window" 1200 40
xdotool mousemove 1100 950
sleep 1
kill -0 "$app_pid" "$demo_pid"
echo 'Packaged application and demo started on virtual X11'

# Click Add console and exercise the actual region picker.
xdotool windowactivate --sync "$app_window"
xdotool mousemove --window "$app_window" 95 778 click 1
sleep 1
xdotool mousemove 1210 80 mousedown 1 mousemove 2080 360 mouseup 1
sleep 0.5
xdotool windowactivate --sync "$demo_window"
xdotool mousemove 1100 950

journal="$XDG_CONFIG_HOME/console-clicker/approvals.log"
for attempt in {1..40}; do
    if [ -f "$journal" ] && grep -q 'demo operation 1' "$journal"; then break; fi
    kill -0 "$app_pid" "$demo_pid"
    sleep 0.5
done
test -f "$journal"
grep -q 'demo operation 1' "$journal"
echo 'Real screen capture, prompt detection, Enter delivery and approval logging passed'

# Read the demo's visible confirmation through the bundled OCR executable.
import -window "$demo_window" /tmp/clicker-demo.png
status=0
"$app" --check-image /tmp/clicker-demo.png >/tmp/clicker-demo-ocr.json || status=$?
test "$status" -eq 0 -o "$status" -eq 2
cat /tmp/clicker-demo-ocr.json
grep -Eq 'Confirmations( received)?: [1-9][0-9]*' /tmp/clicker-demo-ocr.json

# The emergency shortcut should stop approvals even as the next prompt appears.
xdotool key ctrl+alt+q
sleep 1
before=$(wc -l < "$journal")
sleep 6
test "$(wc -l < "$journal")" -eq "$before"
kill -0 "$app_pid" "$demo_pid"
echo 'Emergency stop passed; all packaged Docker checks passed'
