#!/bin/bash

pkill -f 'python etbot.py'

cd "$(dirname $0)"
nohup python etbot.py > "$(dirname $0)/etbot.log" &
disown

sleep 1
ps ax | grep etbot.py | grep -v grep
