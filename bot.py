import os
import json
import time
import threading
import websocket
import logging
from datetime import datetime
from typing import List
import signal
import sys

# Constants
DISCORD_GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)


# -------------------- DISCORD CLIENT --------------------
class DiscordClient:
    def __init__(self, token: str, token_index: int):
        self.token = token
        self.token_index = token_index
        self.ws = None
        self.heartbeat_interval = None
        self.heartbeat_thread = None
        self.should_stop = False
        self.connected = False
        self.last_heartbeat = None
        self.user_data = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5

    def connect(self):
        """Connect to Discord gateway"""
        self.should_stop = False
        self.connected = False
        
        while not self.should_stop and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                logging.info(f"[Token {self.token_index}] Connecting to Discord...")
                
                self.ws = websocket.WebSocketApp(
                    DISCORD_GATEWAY,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                self.ws.run_forever()
                
                # If we reach here, connection was closed
                if not self.should_stop:
                    self.reconnect_attempts += 1
                    if self.reconnect_attempts < self.max_reconnect_attempts:
                        wait_time = min(30, 5 * self.reconnect_attempts)
                        logging.info(f"[Token {self.token_index}] Reconnecting in {wait_time}s... (attempt {self.reconnect_attempts})")
                        time.sleep(wait_time)
                    else:
                        logging.error(f"[Token {self.token_index}] Max reconnect attempts reached")
                        break
                        
            except Exception as e:
                logging.error(f"[Token {self.token_index}] Connection failed: {e}")
                
                if not self.should_stop:
                    self.reconnect_attempts += 1
                    if self.reconnect_attempts < self.max_reconnect_attempts:
                        time.sleep(10)
                    else:
                        break

    def stop(self):
        """Stop the client"""
        logging.info(f"[Token {self.token_index}] Stopping client...")
        self.should_stop = True
        self.connected = False
        if self.ws:
            self.ws.close()

    def is_healthy(self) -> bool:
        """Check if client is healthy"""
        if not self.connected or self.should_stop:
            return False

        if self.last_heartbeat and self.heartbeat_interval:
            time_since_heartbeat = (datetime.now() - self.last_heartbeat).total_seconds()
            if time_since_heartbeat > (self.heartbeat_interval / 1000) * 3:
                return False

        return True

    def on_open(self, ws):
        logging.info(f"[Token {self.token_index}] Connected to Discord Gateway")
        self.connected = True
        self.reconnect_attempts = 0  # Reset on successful connection

    def heartbeat(self):
        """Send heartbeat to keep connection alive"""
        while (self.heartbeat_interval and self.ws and self.ws.sock and
               self.ws.sock.connected and not self.should_stop):
            try:
                self.ws.send(json.dumps({"op": 1, "d": None}))
                self.last_heartbeat = datetime.now()
                time.sleep(self.heartbeat_interval / 1000)
            except Exception as e:
                logging.error(f"[Token {self.token_index}] Heartbeat error: {e}")
                break

    def on_message(self, ws, message):
        try:
            packet = json.loads(message)
            op, event, data = packet.get("op"), packet.get("t"), packet.get("d")

            if op == 10:  # Hello - start heartbeat
                self.heartbeat_interval = data["heartbeat_interval"]
                logging.info(f"[Token {self.token_index}] Starting heartbeat ({self.heartbeat_interval}ms)")
                
                if self.heartbeat_thread:
                    self.heartbeat_thread = None
                self.heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True)
                self.heartbeat_thread.start()

                # Send identify payload
                identify_payload = {
                    "op": 2,
                    "d": {
                        "token": self.token,
                        "intents": 513,  # Basic intents for staying online
                        "properties": {
                            "$os": "Windows",
                            "$browser": "Discord Client",
                            "$device": "desktop"
                        },
                        "presence": {
                            "status": "online",
                            "since": None,
                            "activities": [],
                            "afk": False
                        }
                    }
                }
                ws.send(json.dumps(identify_payload))

            elif event == "READY":
                user = data["user"]
                self.user_data = user
                username = f"{user['username']}#{user.get('discriminator', '0000')}"
                logging.info(f"[Token {self.token_index}] Now online as {username}")

            elif op == 11:  # Heartbeat ACK
                # Heartbeat acknowledged - connection is healthy
                pass

        except json.JSONDecodeError as e:
            logging.error(f"[Token {self.token_index}] Failed to decode message: {e}")
        except Exception as e:
            logging.error(f"[Token {self.token_index}] Error processing message: {e}")

    def on_error(self, ws, error):
        logging.error(f"[Token {self.token_index}] WebSocket error: {error}")

    def on_close(self, ws, code, msg):
        self.connected = False
        logging.warning(f"[Token {self.token_index}] Connection closed (code: {code}, message: {msg})")


# -------------------- ONLINE MANAGER --------------------
class OnlineManager:
    def __init__(self, tokens: List[str]):
        self.tokens = tokens
        self.clients = []
        self.threads = []
        self.should_stop = False
        
        logging.info(f"Initialized OnlineManager with {len(self.tokens)} tokens")

    def start_all_clients(self):
        """Start Discord clients for all tokens"""
        logging.info(f"Starting online clients for {len(self.tokens)} tokens...")

        for i, token in enumerate(self.tokens, 1):
            logging.info(f"Starting client {i}/{len(self.tokens)}...")
            
            client = DiscordClient(token, i)
            
            def run_client(c=client):
                c.connect()

            thread = threading.Thread(target=run_client, daemon=True)
            thread.start()

            self.clients.append(client)
            self.threads.append(thread)
            
            # Stagger connections to avoid rate limits
            if i < len(self.tokens):
                time.sleep(5)

        logging.info(f"All {len(self.clients)} clients started!")
        return self.monitor_clients()

    def monitor_clients(self):
        """Monitor client health and provide status updates"""
        logging.info("Monitoring connections... Press Ctrl+C to stop all clients")
        
        try:
            while not self.should_stop:
                # Count connected clients
                connected_count = sum(1 for c in self.clients if c.connected and not c.should_stop)
                total_count = len(self.clients)
                
                # Log status every 5 minutes
                logging.info(f"Status: {connected_count}/{total_count} clients online")
                
                # Check for dead threads and restart if needed
                for i, (client, thread) in enumerate(zip(self.clients, self.threads)):
                    if not thread.is_alive() and not client.should_stop:
                        logging.warning(f"Thread for token {client.token_index} died, restarting...")
                        self.restart_client(i)
                
                # Wait 5 minutes before next check
                time.sleep(300)

        except KeyboardInterrupt:
            logging.info("Shutdown requested by user")
            self.stop_all_clients()
        
        return True

    def restart_client(self, client_index: int):
        """Restart a specific client"""
        try:
            old_client = self.clients[client_index]
            old_client.stop()
            
            # Wait for cleanup
            time.sleep(3)
            
            # Create new client with same token
            token = self.tokens[client_index]
            new_client = DiscordClient(token, client_index + 1)
            
            def run_new_client():
                new_client.connect()

            new_thread = threading.Thread(target=run_new_client, daemon=True)
            new_thread.start()
            
            self.clients[client_index] = new_client
            self.threads[client_index] = new_thread
            
            logging.info(f"Restarted client for token {client_index + 1}")
            
        except Exception as e:
            logging.error(f"Failed to restart client {client_index + 1}: {e}")

    def stop_all_clients(self):
        """Stop all clients"""
        logging.info("Stopping all clients...")
        self.should_stop = True
        
        for client in self.clients:
            client.stop()
        
        # Wait a moment for graceful shutdown
        time.sleep(2)
        logging.info("All clients stopped")

    def get_status(self):
        """Get current status of all clients"""
        status = {
            "total": len(self.clients),
            "connected": sum(1 for c in self.clients if c.connected),
            "healthy": sum(1 for c in self.clients if c.is_healthy()),
            "clients": []
        }
        
        for client in self.clients:
            client_status = {
                "token_index": client.token_index,
                "connected": client.connected,
                "healthy": client.is_healthy(),
                "username": client.user_data.get("username") if client.user_data else None
            }
            status["clients"].append(client_status)
        
        return status


# -------------------- CONFIGURATION --------------------
def load_config(config_path: str = "tokens.json"):
    """Load configuration from JSON file"""
    if not os.path.exists(config_path):
        return None
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in {config_path}: {e}")
        return None
    except Exception as e:
        logging.error(f"Error loading {config_path}: {e}")
        return None


def create_example_config(config_path: str = "tokens.json"):
    """Create example configuration file"""
    example_config = {
        "tokens": [
            "YOUR_DISCORD_TOKEN_1_HERE",
            "YOUR_DISCORD_TOKEN_2_HERE",
            "YOUR_DISCORD_TOKEN_3_HERE",
            "YOUR_DISCORD_TOKEN_4_HERE",
            "YOUR_DISCORD_TOKEN_5_HERE"
        ]
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(example_config, f, indent=2, ensure_ascii=False)

    logging.info(f"Created example {config_path}")


def extract_tokens(config: dict) -> List[str]:
    """Extract tokens from configuration"""
    tokens = []
    
    if "tokens" in config and isinstance(config["tokens"], list):
        for token in config["tokens"]:
            if isinstance(token, str) and len(token.strip()) > 20:
                tokens.append(token.strip())
    
    return tokens


# -------------------- MAIN --------------------
def main():
    """Main function"""
    CONFIG_FILE = "tokens.json"
    
    try:
        # Check for config file
        if not os.path.exists(CONFIG_FILE):
            logging.info(f"{CONFIG_FILE} not found, creating example...")
            create_example_config(CONFIG_FILE)
            print(f"\nExample configuration created: {CONFIG_FILE}")
            print("Please edit the file with your tokens, then run again.")
            return

        # Load configuration
        config = load_config(CONFIG_FILE)
        if not config:
            logging.error("Failed to load configuration")
            return

        # Extract tokens
        tokens = extract_tokens(config)
        if not tokens:
            logging.error("No valid tokens found in configuration")
            print(f"Please add your Discord tokens to {CONFIG_FILE}")
            return

        # Initialize manager
        manager = OnlineManager(tokens)
        
        print(f"\nLoaded {len(tokens)} tokens")
        print("\nStarting Discord Online Manager...")
        print("All tokens will be kept online until you press Ctrl+C")
        
        # Setup signal handlers
        def signal_handler(signum, frame):
            logging.info(f"Received signal {signum}, shutting down...")
            manager.stop_all_clients()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start and monitor clients
        manager.start_all_clients()

    except KeyboardInterrupt:
        logging.info("Interrupted by user")
    except Exception as e:
        logging.error(f"Script error: {e}")


if __name__ == "__main__":
    main()
