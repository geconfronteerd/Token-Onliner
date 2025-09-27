import os
import json
import time
import threading
import requests
import websocket
import logging
from datetime import datetime
from typing import List, Dict
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

# Global debug webhook manager
debug_webhook = None


# -------------------- DEBUG WEBHOOK MANAGER --------------------
class DebugWebhookManager:
    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)
        self.max_retries = 3
        self.retry_delay = 2

    def send_debug(self, title: str, description: str, color: int = 0xFF5555, fields: List[Dict] = None):
        """Send debug message to webhook with retry logic"""
        if not self.enabled:
            return

        for attempt in range(self.max_retries):
            try:
                embed = {
                    "title": f"🟢 {title}",
                    "description": description[:4000],
                    "color": color,
                    "timestamp": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                    "footer": {"text": "Discord Online Manager"}
                }

                if fields:
                    embed["fields"] = fields

                payload = {
                    "embeds": [embed],
                    "username": "Discord Online Manager"
                }

                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10,
                    headers={'Content-Type': 'application/json'}
                )

                if response.status_code == 204:
                    return
                elif response.status_code == 429:
                    retry_after = response.json().get('retry_after', self.retry_delay)
                    logging.warning(f"Debug webhook rate limited, retrying after {retry_after}s")
                    time.sleep(retry_after)
                    continue
                else:
                    logging.warning(f"Debug webhook failed: {response.status_code}")

            except Exception as e:
                logging.error(f"Debug webhook error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))

    def send_startup(self, token_count: int):
        """Send startup notification"""
        self.send_debug(
            "Online Manager Started",
            f"Starting Discord Online Manager with {token_count} tokens",
            color=0x00FF00,
            fields=[
                {"name": "Tokens", "value": str(token_count), "inline": True},
                {"name": "Status", "value": "Starting", "inline": True}
            ]
        )

    def send_token_event(self, token_index: int, event: str, details: str = ""):
        """Send token event notification"""
        colors = {
            "connected": 0x00FF00,
            "disconnected": 0xFF5555,
            "error": 0xFF0000,
            "reconnecting": 0xFFAA00,
            "online": 0x00FF00
        }

        self.send_debug(
            f"Token {token_index} - {event.title()}",
            details or f"Token {token_index} {event}",
            color=colors.get(event, 0x5865F2)
        )

    def send_shutdown(self):
        """Send shutdown notification"""
        self.send_debug("Online Manager Stopped", "All tokens have been disconnected", color=0xFFAA00)


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

        global debug_webhook
        self.debug_webhook = debug_webhook

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
                        if self.debug_webhook:
                            self.debug_webhook.send_token_event(
                                self.token_index, 
                                "error", 
                                "Max reconnect attempts reached - giving up"
                            )
                        break
                        
            except Exception as e:
                logging.error(f"[Token {self.token_index}] Connection failed: {e}")
                if self.debug_webhook:
                    self.debug_webhook.send_token_event(self.token_index, "error", f"Connection failed: {str(e)}")
                
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
        
        if self.debug_webhook:
            self.debug_webhook.send_token_event(self.token_index, "connected", "Connected to Discord Gateway")

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
                            "os": "linux",
                            "browser": "custom",
                            "device": "custom"
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
                
                if self.debug_webhook:
                    self.debug_webhook.send_token_event(
                        self.token_index, 
                        "online", 
                        f"Successfully online as {username}\nID: {user['id']}"
                    )

            elif op == 11:  # Heartbeat ACK
                # Heartbeat acknowledged - connection is healthy
                pass

        except json.JSONDecodeError as e:
            logging.error(f"[Token {self.token_index}] Failed to decode message: {e}")
        except Exception as e:
            logging.error(f"[Token {self.token_index}] Error processing message: {e}")

    def on_error(self, ws, error):
        logging.error(f"[Token {self.token_index}] WebSocket error: {error}")
        if self.debug_webhook:
            self.debug_webhook.send_token_event(self.token_index, "error", f"WebSocket error: {str(error)}")

    def on_close(self, ws, code, msg):
        self.connected = False
        logging.warning(f"[Token {self.token_index}] Connection closed (code: {code}, message: {msg})")
        
        if self.debug_webhook and not self.should_stop:
            self.debug_webhook.send_token_event(
                self.token_index, 
                "disconnected", 
                f"Connection closed - Code: {code}"
            )


# -------------------- ONLINE MANAGER --------------------
class OnlineManager:
    def __init__(self, tokens: List[str], debug_webhook_url: str = None):
        self.tokens = tokens
        self.debug_webhook = DebugWebhookManager(debug_webhook_url)
        self.clients = []
        self.threads = []
        self.should_stop = False
        
        global debug_webhook
        debug_webhook = self.debug_webhook
        
        logging.info(f"Initialized OnlineManager with {len(self.tokens)} tokens")

    def start_all_clients(self):
        """Start Discord clients for all tokens"""
        logging.info(f"Starting online clients for {len(self.tokens)} tokens...")
        
        if self.debug_webhook:
            self.debug_webhook.send_startup(len(self.tokens))

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
        
        if self.debug_webhook:
            self.debug_webhook.send_shutdown()
        
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
        "debug_webhook_url": "https://discord.com/api/webhooks/YOUR_WEBHOOK_URL_HERE",
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
            print("Please edit the file with your tokens and webhook URL, then run again.")
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

        # Get debug webhook URL
        debug_webhook_url = config.get("debug_webhook_url")
        if debug_webhook_url and not debug_webhook_url.startswith("https://"):
            debug_webhook_url = None

        # Initialize manager
        manager = OnlineManager(tokens, debug_webhook_url)
        
        print(f"\nLoaded {len(tokens)} tokens")
        if debug_webhook_url:
            print("Debug webhook: enabled")
        else:
            print("Debug webhook: disabled")
        
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
        if debug_webhook:
            debug_webhook.send_debug("Script Error", f"Unexpected error: {str(e)}", color=0xFF0000)


if __name__ == "__main__":
    main()
