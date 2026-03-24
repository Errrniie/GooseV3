#!/bin/bash
# quick_start.sh - Launch the Goose Deterrence System

echo "======================================================================"
echo "GOOSE DETERRENCE SYSTEM - QUICK START"
echo "======================================================================"
echo ""
echo "Pre-flight checklist:"
echo "  [1] Printer powered ON and connected to network"
echo "  [2] ESP32 laser controller powered ON (see Config/network_config.py for IP)"
echo "  [3] Camera connected (USB)"
echo "  [4] Measuring tape ready for calibration"
echo ""
echo "Starting system..."
echo ""

cd /home/LxSparda/Desktop/GooseProject
python SystemMain.py
