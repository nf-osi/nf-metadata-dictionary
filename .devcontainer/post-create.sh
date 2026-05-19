#!/bin/bash

pip install linkml==v1.8.1
npm install -g json-dereference-cli
sudo bash < <(curl -s https://raw.githubusercontent.com/babashka/babashka/master/install)
git clone --depth 1 https://github.com/anngvu/retold.git

