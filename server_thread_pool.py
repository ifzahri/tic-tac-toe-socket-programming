import socket
import threading
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from http import HttpHandler

logging.basicConfig(level=logging.INFO)

class ThreadPoolHTTPServer:
    def __init__(self, host="localhost", port=55556, max_workers=10, state_file="game_state.json"):
        self.host = host
        self.port = port
        self.max_workers = max_workers
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Initialize HTTP handler
        self.http_handler = HttpHandler(state_file)
        
        # Thread pool executor
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # Server running flag
        self.running = False
        
        # Lock for thread-safe access to shared game state
        self.lock = threading.Lock()

    def start_server(self):
        """Start the HTTP server with thread pool"""
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            self.running = True
            logging.info(f"Tic Tac Toe HTTP Server started on {self.host}:{self.port} with {self.max_workers} workers")

            # Start reaper thread for inactive players
            reaper_thread = threading.Thread(target=self.reap_inactive_players)
            reaper_thread.daemon = True
            reaper_thread.start()

            # Accept connections and handle them using thread pool
            while self.running:
                try:
                    client_socket, address = self.socket.accept()
                    logging.info(f"Connection from {address}")
                    
                    # Submit request handling to thread pool
                    future = self.executor.submit(self.handle_request, client_socket)
                    
                except socket.error as e:
                    if self.running:
                        logging.error(f"Socket error: {e}")
                    break
                except Exception as e:
                    logging.error(f"Error accepting connection: {e}")
                    break

        except Exception as e:
            logging.error(f"Error starting server: {e}")
        finally:
            self.shutdown()

    def handle_request(self, client_socket):
        """Handle individual client request"""
        try:
            # Set socket timeout
            client_socket.settimeout(30)
            
            # Receive request data
            request_data = client_socket.recv(4096).decode("utf-8")
            if not request_data:
                return

            # Process request using HTTP handler with thread-safe lock
            with self.lock:
                response = self.http_handler.process_request(request_data)
            
        except socket.timeout:
            logging.warning("Client request timed out")
            response = self.http_handler.create_response(
                408, "Request Timeout", {"status": "ERROR", "message": "Request timeout"}
            )
        except Exception as e:
            logging.error(f"Error handling request: {e}")
            response = self.http_handler.create_response(
                500, "Internal Server Error", {"status": "ERROR", "message": str(e)}
            )
        finally:
            try:
                client_socket.sendall(response)
            except Exception as e:
                logging.error(f"Error sending response: {e}")
            finally:
                client_socket.close()

    def reap_inactive_players(self):
        """Background thread to check for inactive players"""
        while self.running:
            try:
                time.sleep(5)
                with self.lock:
                    self.http_handler.check_inactive_players()
            except Exception as e:
                logging.error(f"Error in reaper thread: {e}")
                
    def shutdown(self):
        """Gracefully shutdown the server"""
        logging.info("Shutting down server...")
        self.running = False
        
        # Save game state before shutdown
        try:
            with self.lock:
                self.http_handler.save_game_state()
        except Exception as e:
            logging.error(f"Error saving game state during shutdown: {e}")
        
        # Shutdown thread pool
        try:
            self.executor.shutdown(wait=True, timeout=10)
        except Exception as e:
            logging.error(f"Error shutting down thread pool: {e}")
        
        # Close socket
        try:
            self.socket.close()
        except Exception as e:
            logging.error(f"Error closing socket: {e}")
        
        logging.info("Server shutdown complete.")

    def get_server_stats(self):
        """Get server statistics"""
        return {
            "host": self.host,
            "port": self.port,
            "max_workers": self.max_workers,
            "running": self.running,
            "active_games": len(self.http_handler.games),
            "registered_players": len(self.http_handler.players),
        }

if __name__ == "__main__":
    server = ThreadPoolHTTPServer()
    try:
        server.start_server()
    except KeyboardInterrupt:
        logging.info("Received interrupt signal...")
        server.shutdown()
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        server.shutdown()