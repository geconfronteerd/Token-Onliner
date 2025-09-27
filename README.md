# Token-Onliner

**Token-Onliner** is a Python script that demonstrates how to connect multiple WebSocket clients to a gateway, keep them alive with heartbeats, and automatically handle reconnections. It includes monitoring and restart logic to ensure stable long-running connections.

---

## Features

* Connects multiple clients via WebSocket
* Maintains heartbeat intervals automatically
* Handles reconnects with backoff strategy
* Tracks client health and status
* Monitors and restarts clients if they die
* Configurable via a simple `tokens.json` file

---

## Requirements

* Python 3.8+
* Dependencies:

  * `websocket-client`
  * `typing-extensions` (for some environments)
  * Standard library modules: `os`, `json`, `time`, `threading`, `logging`, etc.

Install dependencies with:

```bash
pip install websocket-client
```

---

## Setup

1. Clone this repository:

   ```bash
   git clone https://github.com/geconfronteerd/token-onliner
   cd token-onliner
   ```

2. Create or edit the `tokens.json` configuration file:

   ```json
   {
     "tokens": [
       "TOKEN_1",
       "TOKEN_2",
       "TOKEN_3"
     ]
   }
   ```

3. Run the script:

   ```bash
   python main.py
   ```

---

## Configuration

* `tokens.json` holds the list of tokens (or identifiers) you want to connect with.
* Example structure:

  ```json
  {
    "tokens": [
      "EXAMPLE_TOKEN_A",
      "EXAMPLE_TOKEN_B"
    ]
  }
  ```

---

## Monitoring

* The script logs connection status, health checks, and heartbeat events.
* Clients are automatically restarted if a connection drops unexpectedly.

---

## Disclaimer

Please read the [Disclaimer](./DISCLAIMER.md) before using this project.  
Use at your own risk. The author is not responsible for any consequences.
