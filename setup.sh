#!/bin/bash
# Simple setup script for tetra-decode
set -e
sudo apt-get update
sudo apt-get install -y rtl-sdr osmocom-tetra python3-pip
pip3 install -r requirements.txt
