import socket
import threading
import logging
import time
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from http import HttpServer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s')

class ThreadPoolHTTPServer:
    def __init__(self, host="localhost", port=55556, max_workers=10):
        self.host = host
        self.port = port
        self.max_workers = max_workers
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.http_server = HttpServer()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='Worker')
        self.running = False
        self.lock = threading.Lock()

    def start_server(self):
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            self.running = True
            logging.info(f"Server starting on {self.host}:{self.port} with {self.max_workers} workers")
            while self.running:
                try:
                    client_socket, address = self.socket.accept()
                    logging.info(f"Accepted connection from {address}")
                    self.executor.submit(self.handle_request, client_socket, address)
                except OSError:
                    if self.running: logging.error("Socket error on accept()")
                    break
        except Exception as e:
            logging.error(f"Failed to start server: {e}")
        finally:
            self.shutdown()

    def handle_request(self, client_socket, address):
        logging.info(f"Handler started for {address}")
        response = None
        try:
            client_socket.settimeout(10)
            request_data = client_socket.recv(4096).decode("utf-8")

            if not request_data:
                logging.warning(f"No data received from {address}. Closing connection.")
                return

            logging.info(f"Received {len(request_data)} bytes from {address}")

            with self.lock:
                logging.info(f"Acquired lock for processing request from {address}")
                response = self.http_server.proses(request_data)
                logging.info(f"Releasing lock for {address}")

        except socket.timeout:
            logging.warning(f"Request from {address} timed out.")
            response = self.http_server.response(408, "Request Timeout", {"status": "ERROR", "message": "Request timeout"})
        except ConnectionResetError:
            logging.warning(f"Connection reset by {address} during recv.")
        except Exception as e:
            logging.error(f"Error handling request from {address}: {e}", exc_info=True)
            response = self.http_server.response(500, "Internal Server Error", {"status": "ERROR", "message": str(e)})
        finally:
            if response:
                try:
                    client_socket.sendall(response)
                    logging.info(f"Response sent to {address}")
                except Exception as e:
                    logging.error(f"Error sending response to {address}: {e}")

            logging.info(f"Closing connection for {address}")
            client_socket.close()

    def shutdown(self):
        logging.info("Shutting down server...")
        self.running = False
        self.executor.shutdown(wait=True)
        self.socket.close()
        logging.info("Server shutdown complete.")


def get_server_config():
    """Get server configuration from command line arguments and environment variables"""
    parser = argparse.ArgumentParser(description='TicTacToe HTTP Server with Thread Pool')
    
    # Command line arguments
    parser.add_argument('--host', '-H', 
                       default=os.getenv('TICTACTOE_HOST', 'localhost'),
                       help='Server host address (default: localhost, env: TICTACTOE_HOST)')
    
    parser.add_argument('--port', '-p', 
                       type=int,
                       default=int(os.getenv('TICTACTOE_PORT', '55556')),
                       help='Server port number (default: 55556, env: TICTACTOE_PORT)')
    
    parser.add_argument('--workers', '-w',
                       type=int, 
                       default=int(os.getenv('TICTACTOE_WORKERS', '10')),
                       help='Maximum number of worker threads (default: 10, env: TICTACTOE_WORKERS)')
    
    parser.add_argument('--log-level', '-l',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       default=os.getenv('TICTACTOE_LOG_LEVEL', 'INFO'),
                       help='Logging level (default: INFO, env: TICTACTOE_LOG_LEVEL)')
    
    args = parser.parse_args()
    
    if not (1 <= args.port <= 65535):
        print(f"Error: Port {args.port} is not valid. Must be between 1 and 65535.")
        sys.exit(1)
    
    if args.workers < 1:
        print(f"Error: Workers {args.workers} is not valid. Must be at least 1.")
        sys.exit(1)
    
    numeric_level = getattr(logging, args.log_level)
    logging.getLogger().setLevel(numeric_level)
    
    return args


def check_port_availability(host, port):
    """Check if the specified port is available for binding"""
    try:
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        test_socket.bind((host, port))
        test_socket.close()
        return True
    except socket.error as e:
        logging.error(f"Port {port} is not available: {e}")
        return False


def find_available_port(host, start_port, max_attempts=10):
    """Find an available port starting from start_port"""
    for port in range(start_port, start_port + max_attempts):
        if check_port_availability(host, port):
            logging.info(f"Found available port: {port}")
            return port
    return None


def main():
    """Main function with dynamic configuration support"""
    try:
        config = get_server_config()
        
        logging.info(f"Starting TicTacToe Server with configuration:")
        logging.info(f"  Host: {config.host}")
        logging.info(f"  Port: {config.port}")
        logging.info(f"  Workers: {config.workers}")
        logging.info(f"  Log Level: {config.log_level}")
        
        if not check_port_availability(config.host, config.port):
            logging.warning(f"Port {config.port} is not available, searching for alternative...")
            alternative_port = find_available_port(config.host, config.port + 1)
            
            if alternative_port:
                logging.info(f"Using alternative port: {alternative_port}")
                config.port = alternative_port
            else:
                logging.error("No available ports found")
                sys.exit(1)
        
        server = ThreadPoolHTTPServer(
            host=config.host,
            port=config.port,
            max_workers=config.workers
        )
        
        server.start_server()
        
    except KeyboardInterrupt:
        logging.info("Received interrupt signal...")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()