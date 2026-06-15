#!/usr/bin/env python3
import sys
import requests
import json
import argparse

SERVER_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 5

def get_status():
    try:
        res = requests.get(f"{SERVER_URL}/api/state", timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            state = res.json()
            print("\n--- Server State ---")
            print(f"Status:        {state['status']}")
            print(f"Active Input:  {state.get('active_input', '-')}")
            print("\n--- Worker Pool ---")
            workers = state.get("workers", [])
            if not workers:
                print("No workers connected.")
            for w in workers:
                print(f"Worker: {w['name']} | ID: {w['id'][:8]}... | Status: {w['status']}")
            print("--------------------\n")
        else:
            print(f"Error: Server returned status code {res.status_code}")
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the server. Is it running?")

def stop_simulation():
    try:
        res = requests.post(f"{SERVER_URL}/api/stop-simulation", timeout=REQUEST_TIMEOUT)
        print(res.json().get("message", "Unknown response from server."))
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the server.")

def shutdown_server():
    try:
        print("Sending shutdown command...")
        res = requests.post(f"{SERVER_URL}/api/shutdown", timeout=REQUEST_TIMEOUT)
        print(res.json().get("status", "Unknown response"))
    except requests.exceptions.ConnectionError:
        print("Server disconnected (likely shut down successfully).")

def main():
    parser = argparse.ArgumentParser(description="SimC Helper Debug CLI")
    parser.add_argument("command", choices=["status", "stop-sim", "shutdown"], help="Command to execute")

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    if args.command == "status":
        get_status()
    elif args.command == "stop-sim":
        stop_simulation()
    elif args.command == "shutdown":
        shutdown_server()

if __name__ == "__main__":
    main()
