#!/bin/bash
export DISPLAY=:0
export XAUTHORITY=/home/james/.Xauthority
export XDG_RUNTIME_DIR=/run/user/1000
mkdir -p /run/user/1000
chmod 700 /run/user/1000
chown james:james /run/user/1000
pkill -f field-launcher 2>/dev/null
sleep 1
python3 /usr/local/bin/field-launcher > /home/james/launcher.log 2>&1 &
echo $! > /tmp/field-launcher.pid
