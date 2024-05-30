#!/bin/bash

pip3 install schematicpy==24.5.1 ipython==8.18.1
sudo bash < <(curl -s https://raw.githubusercontent.com/babashka/babashka/master/install)
git clone --depth 1 https://github.com/anngvu/retold.git

