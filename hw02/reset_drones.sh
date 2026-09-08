#!/bin/bash
# Reset drone positions by restarting Docker containers

echo "=== Resetting Drone Positions ==="

# Go to lab directory
cd ~/uav-native-ai/lab

# Stop all containers
echo "Stopping drones..."
docker compose down

# Restart containers
echo "Starting drones..."
docker compose up -d --remove-orphans

# Wait for initialization
echo "Waiting for drones to initialize..."
sleep 15

# Check status
echo "Drone status:"
docker compose ps

echo "=== Reset Complete! ==="
echo "Drones are back at their home positions."
