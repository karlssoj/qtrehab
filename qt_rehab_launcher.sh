#!/bin/bash

# Check that a movement folder argument was provided
if [ -z "$1" ]; then
    echo "Usage: $0 <movement_folder>"
    echo "Example: $0 hukning_fr_n_sidan"
    exit 1
fi

MOVEMENT="$1"

#Activate the environment
source /home/qtrobot/dev/An_project/ollamaenv/bin/activate
source /opt/ros/noetic/setup.bash
source /home/qtrobot/catkin_ws/devel/setup.bash

# Start roscore only if it is not already running
if ! pgrep -x "roscore" > /dev/null
then
    echo "Starting roscore ..."
    roscore &
    sleep 2
else
    echo "roscore already running."
fi

cd /home/qtrobot/catkin_ws/src/qt_rehab/qtrehab

rosrun qt_rehab "$MOVEMENT/run.py"
echo "Finished"
read -p "Press Enter to close.."