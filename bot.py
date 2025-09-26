import os
import json
import time
import threading
import requests
import logging
from datetime import datetime
from typing import Optional, Dict, List

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
                    "title": f"🔧 Debug: {title}",
                    "description": description[:4000],  # Discord limit
                    "color": color,
                    "timestamp": datetime.utcnow().isoformat(),
                    "footer": {"text": "Token One-Liner Debug System"}
                }

                if fields:
                    embed["fields"] = fields

                payload = {
                    "embeds": [embed],
                    "username": "Token One-Liner Debug"
                }

                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10,
                    headers={'Content-Type': 'application/json'}
                )

                if response.status_code == 204:
                    return  # Success
                elif response.status_code == 429:  # Rate limited
                    retry_after = response.json().get('retry_after', self.retry_delay)
                    logging.warning(f"Debug webhook rate limited, retrying after {retry_after}s")
                    time.sleep(retry_after)
                    continue
                else:
                    logging.warning(f"Debug webhook failed: {response.status_code} - {response.text[:100]}")

            except Exception as e:
                logging.error(f"Debug webhook error (attempt {attempt + 1}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))

    def send_startup(self, token_count: int):
        """Send startup notification"""
        self.send_debug(
            "Token One-Liner Started",
            f"Token one-liner has started successfully with {token_count} tokens",
            color=0x00FF00,
            fields=[
                {"name": "Tokens Loaded", "value": str(token_count), "inline": True},
                {"name": "Status", "value": "Running", "inline": True}
            ]
        )

    def send_shutdown(self, reason: str = "Manual shutdown"):
        """Send shutdown notification"""
        self.send_debug("Token One-Liner Stopped", reason, color=0xFFAA00)

    def send_token_event(self, token_index: int, event: str, details: str = ""):
        """Send token event notification"""
        colors = {
            "success": 0x00FF00,
            "error": 0xFF0000,
            "warning": 0xFFAA00,
            "info": 0x5865F2
        }

        self.send_debug(
            f"Token {token_index} - {event.title()}",
            details or f"Token {token_index} {event}",
            color=colors.get(event, 0x5865F2)
        )

# -------------------- MULTI-TOKEN MANAGER --------------------
class MultiTokenManager:
    def __init__(self, tokens: List[str], debug_webhook_url: str = None):
        self.tokens = tokens
        self.debug_webhook = DebugWebhookManager(debug_webhook_url)
        self.results = {}
        self.threads = []
        
        global debug_webhook
        debug_webhook = self.debug_webhook
        
        logging.info(f"Initialized MultiTokenManager with {len(self.tokens)} tokens")

    def load_tokens_from_config(self, config_path: str = "tokens.json") -> List[str]:
        """Load tokens from a JSON configuration file"""
        tokens = []
        
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                
                # Support multiple config formats
                if isinstance(config, list):
                    # Array of token objects: [{"token": "..."}, {"token": "..."}, ...]
                    for i, token_config in enumerate(config):
                        if isinstance(token_config, dict) and "token" in token_config:
                            token = token_config["token"].strip()
                            if token:
                                tokens.append(token)
                                logging.info(f"Loaded token {i + 1} from config")
                        elif isinstance(token_config, str) and token_config.strip():
                            # Simple string array: ["token1", "token2", ...]
                            tokens.append(token_config.strip())
                            logging.info(f"Loaded token {i + 1} from config")
                
                elif isinstance(config, dict):
                    # Object with tokens array: {"tokens": ["...", "...", ...]}
                    if "tokens" in config and isinstance(config["tokens"], list):
                        for i, token in enumerate(config["tokens"]):
                            if isinstance(token, str) and token.strip():
                                tokens.append(token.strip())
                                logging.info(f"Loaded token {i + 1} from config")
                    
                    # Object with individual token keys: {"token1": "...", "token2": "...", ...}
                    else:
                        for key, value in config.items():
                            if key.startswith("token") and isinstance(value, str) and value.strip():
                                tokens.append(value.strip())
                                logging.info(f"Loaded {key} from config")
                
                logging.info(f"Successfully loaded {len(tokens)} tokens from {config_path}")
                
            except json.JSONDecodeError as e:
                logging.error(f"Invalid JSON in {config_path}: {e}")
            except Exception as e:
                logging.error(f"Error loading tokens from {config_path}: {e}")
        
        return tokens

    def create_example_config(self, config_path: str = "tokens.json"):
        """Create an example tokens configuration file"""
        example_config = {
            "debug_webhook_url": "https://discord.com/api/webhooks/YOUR_DEBUG_WEBHOOK_URL_HERE",
            "tokens": [
                "YOUR_DISCORD_TOKEN_1_HERE",
                "YOUR_DISCORD_TOKEN_2_HERE",
                "YOUR_DISCORD_TOKEN_3_HERE",
                # Add more tokens as needed - supports 30+ easily
                *[f"YOUR_DISCORD_TOKEN_{i}_HERE" for i in range(4, 31)]  # Creates tokens 4-30
            ]
        }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(example_config, f, indent=2, ensure_ascii=False)

        logging.info(f"Created example {config_path} with 30 token slots")

    def validate_token_format(self, token: str) -> bool:
        """Basic token format validation"""
        # Discord bot tokens are typically 24+ chars and contain dots
        # User tokens are typically longer and may contain different patterns
        return len(token) >= 20 and ('.' in token or len(token) >= 50)

    def process_token(self, token: str, token_index: int):
        """Process a single token - customize this method for your specific task"""
        try:
            logging.info(f"Processing token {token_index}...")
            
            # Validate token format
            if not self.validate_token_format(token):
                logging.warning(f"Token {token_index} has invalid format")
                self.results[token_index] = {"status": "error", "message": "Invalid token format"}
                if self.debug_webhook:
                    self.debug_webhook.send_token_event(token_index, "warning", "Invalid token format detected")
                return

            # Example: Make a simple Discord API request to validate token
            headers = {
                "Authorization": f"Bot {token}" if not token.startswith("Bot ") else token,
                "Content-Type": "application/json"
            }

            # Test with Discord API - get current user
            response = requests.get("https://discord.com/api/v10/users/@me", headers=headers, timeout=10)
            
            if response.status_code == 200:
                user_data = response.json()
                username = user_data.get("username", "Unknown")
                user_id = user_data.get("id", "Unknown")
                
                self.results[token_index] = {
                    "status": "success", 
                    "username": username,
                    "user_id": user_id,
                    "token": token[:20] + "..." # Partial token for logging
                }
                
                logging.info(f"Token {token_index} valid - User: {username}#{user_data.get('discriminator', '0000')}")
                
                if self.debug_webhook:
                    self.debug_webhook.send_token_event(
                        token_index, 
                        "success", 
                        f"Token validated successfully\nUser: {username}#{user_data.get('discriminator', '0000')}\nID: {user_id}"
                    )

            elif response.status_code == 401:
                logging.error(f"Token {token_index} is invalid or expired")
                self.results[token_index] = {"status": "error", "message": "Invalid/expired token"}
                
                if self.debug_webhook:
                    self.debug_webhook.send_token_event(token_index, "error", "Token is invalid or expired")

            elif response.status_code == 429:
                logging.warning(f"Token {token_index} rate limited")
                self.results[token_index] = {"status": "error", "message": "Rate limited"}
                
                if self.debug_webhook:
                    self.debug_webhook.send_token_event(token_index, "warning", "Token is rate limited")

            else:
                logging.error(f"Token {token_index} failed with status {response.status_code}")
                self.results[token_index] = {"status": "error", "message": f"HTTP {response.status_code}"}
                
                if self.debug_webhook:
                    self.debug_webhook.send_token_event(token_index, "error", f"HTTP {response.status_code}: {response.text[:100]}")

        except requests.exceptions.RequestException as e:
            logging.error(f"Network error for token {token_index}: {e}")
            self.results[token_index] = {"status": "error", "message": f"Network error: {str(e)}"}
            
            if self.debug_webhook:
                self.debug_webhook.send_token_event(token_index, "error", f"Network error: {str(e)}")

        except Exception as e:
            logging.error(f"Unexpected error for token {token_index}: {e}")
            self.results[token_index] = {"status": "error", "message": f"Unexpected error: {str(e)}"}
            
            if self.debug_webhook:
                self.debug_webhook.send_token_event(token_index, "error", f"Unexpected error: {str(e)}")

    def run_parallel(self, max_threads: int = 10, delay_between_tokens: float = 1.0):
        """Run token processing in parallel with thread limit and delay"""
        logging.info(f"Starting parallel processing with max {max_threads} threads, {delay_between_tokens}s delay")
        
        if self.debug_webhook:
            self.debug_webhook.send_startup(len(self.tokens))

        def worker():
            while True:
                try:
                    token_index, token = thread_queue.get(timeout=1)
                    if token_index is None:  # Sentinel to stop
                        break
                    
                    self.process_token(token, token_index)
                    time.sleep(delay_between_tokens)  # Rate limiting
                    thread_queue.task_done()
                    
                except:
                    break

        # Create queue and start worker threads
        import queue
        thread_queue = queue.Queue()
        
        # Start worker threads
        threads = []
        for _ in range(min(max_threads, len(self.tokens))):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            threads.append(thread)

        # Add tokens to queue
        for i, token in enumerate(self.tokens, 1):
            thread_queue.put((i, token))

        # Wait for all tasks to complete
        thread_queue.join()

        # Stop worker threads
        for _ in threads:
            thread_queue.put((None, None))

        # Wait for threads to finish
        for thread in threads:
            thread.join(timeout=5)

        logging.info("All tokens processed!")
        return self.results

    def run_sequential(self, delay_between_tokens: float = 2.0):
        """Run token processing sequentially with delay"""
        logging.info(f"Starting sequential processing with {delay_between_tokens}s delay")
        
        if self.debug_webhook:
            self.debug_webhook.send_startup(len(self.tokens))

        for i, token in enumerate(self.tokens, 1):
            self.process_token(token, i)
            
            # Add delay between tokens (except for the last one)
            if i < len(self.tokens):
                time.sleep(delay_between_tokens)

        logging.info("All tokens processed!")
        return self.results

    def print_summary(self):
        """Print a summary of results"""
        if not self.results:
            logging.info("No results to summarize")
            return

        successful = sum(1 for r in self.results.values() if r.get("status") == "success")
        failed = len(self.results) - successful

        print("\n" + "="*50)
        print("TOKEN PROCESSING SUMMARY")
        print("="*50)
        print(f"Total Tokens: {len(self.results)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Success Rate: {(successful/len(self.results)*100):.1f}%")
        print("="*50)

        # Print successful tokens
        if successful > 0:
            print("\nSUCCESSFUL TOKENS:")
            print("-" * 30)
            for token_index, result in self.results.items():
                if result.get("status") == "success":
                    username = result.get("username", "Unknown")
                    user_id = result.get("user_id", "Unknown")
                    print(f"Token {token_index}: {username} (ID: {user_id})")

        # Print failed tokens
        if failed > 0:
            print(f"\nFAILED TOKENS ({failed}):")
            print("-" * 30)
            for token_index, result in self.results.items():
                if result.get("status") != "success":
                    message = result.get("message", "Unknown error")
                    print(f"Token {token_index}: {message}")

        print("="*50 + "\n")

# -------------------- MAIN FUNCTION --------------------
def main():
    """Main function - customize this for your specific use case"""
    
    # Configuration
    CONFIG_FILE = "tokens.json"
    DEBUG_WEBHOOK_URL = None  # Will be loaded from config if available
    
    try:
        # Initialize manager
        manager = MultiTokenManager([], DEBUG_WEBHOOK_URL)
        
        # Check if config file exists
        if not os.path.exists(CONFIG_FILE):
            logging.info(f"{CONFIG_FILE} not found, creating example configuration...")
            manager.create_example_config(CONFIG_FILE)
            print(f"\nPlease edit {CONFIG_FILE} and add your tokens, then run the script again.")
            return

        # Load configuration
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                
                # Get debug webhook URL if available
                if isinstance(config, dict) and "debug_webhook_url" in config:
                    DEBUG_WEBHOOK_URL = config["debug_webhook_url"]
                    if DEBUG_WEBHOOK_URL and DEBUG_WEBHOOK_URL.startswith("https://"):
                        manager.debug_webhook = DebugWebhookManager(DEBUG_WEBHOOK_URL)
                        global debug_webhook
                        debug_webhook = manager.debug_webhook
                        logging.info("Debug webhook enabled")

        # Load tokens from config
        tokens = manager.load_tokens_from_config(CONFIG_FILE)
        
        if not tokens:
            logging.error("No valid tokens found in configuration!")
            print(f"Please add your tokens to {CONFIG_FILE}")
            return

        # Update manager with loaded tokens
        manager.tokens = tokens
        
        print(f"\nLoaded {len(tokens)} tokens")
        print("Choose processing mode:")
        print("1. Parallel (faster, max 10 concurrent)")
        print("2. Sequential (safer, slower)")
        
        choice = input("Enter choice (1 or 2): ").strip()
        
        if choice == "1":
            print("Running in parallel mode...")
            results = manager.run_parallel(max_threads=10, delay_between_tokens=1.0)
        else:
            print("Running in sequential mode...")
            results = manager.run_sequential(delay_between_tokens=2.0)
        
        # Print summary
        manager.print_summary()
        
        # Save results to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = f"token_results_{timestamp}.json"
        
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logging.info(f"Results saved to {results_file}")
        
        if debug_webhook:
            debug_webhook.send_shutdown("Processing completed successfully")

    except KeyboardInterrupt:
        logging.info("Script interrupted by user")
        if debug_webhook:
            debug_webhook.send_shutdown("Script interrupted by user")
    
    except Exception as e:
        logging.error(f"Script error: {e}")
        if debug_webhook:
            debug_webhook.send_debug("Script Error", f"Unexpected error: {str(e)}", color=0xFF0000)

if __name__ == "__main__":
    main()
