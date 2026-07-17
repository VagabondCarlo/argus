#!/bin/zsh
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
cd ~/argus_v2
source venv/bin/activate

/opt/homebrew/bin/tmux kill-session -t argus_v2 2>/dev/null

/opt/homebrew/bin/tmux new-session -d -s argus_v2 -n 'analyst'   'source ~/argus_v2/venv/bin/activate && cd ~/argus_v2 && python3 -m analyst.main; read'

/opt/homebrew/bin/tmux new-window -t argus_v2:1 -n 'bot'   'source ~/argus_v2/venv/bin/activate && cd ~/argus_v2 && python3 -m notifications.bot; read'

/opt/homebrew/bin/tmux new-window -t argus_v2:2 -n 'executor'   'source ~/argus_v2/venv/bin/activate && cd ~/argus_v2 && python3 -m executor.main; read'

/opt/homebrew/bin/tmux new-window -t argus_v2:3 -n 'display'   'source ~/argus_v2/venv/bin/activate && cd ~/argus_v2 && python3 display.py; read'

echo 'Argus v2 started.'
