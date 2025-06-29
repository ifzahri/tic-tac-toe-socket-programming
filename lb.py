import socket
import time
import sys
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class BackendServerList:
    """Manages backend TicTacToe servers with round-robin selection"""
    
    def __init__(self):
        self.servers = []
        # Add your TicTacToe server instances here
        self.servers.append(('127.0.0.1', 55556))  # Server 1
        self.servers.append(('127.0.0.1', 55557))  # Server 2  
        self.servers.append(('127.0.0.1', 55558))  # Server 3
        # Add more servers as needed
        
        self.current = 0
        self.lock = threading.Lock()
        
    def get_server(self):
        """Get next server using round-robin algorithm"""
        with self.lock:
            server = self.servers[self.current]
            logging.info(f"Selected backend server: {server}")
            self.current = (self.current + 1) % len(self.servers)
            return server
    
    def health_check(self):
        """Basic health check for backend servers"""
        healthy_servers = []
        for server in self.servers:
            try:
                test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_sock.settimeout(2)
                result = test_sock.connect_ex(server)
                test_sock.close()
                if result == 0:
                    healthy_servers.append(server)
                    logging.debug(f"Server {server} is healthy")
                else:
                    logging.warning(f"Server {server} is unreachable")
            except Exception as e:
                logging.warning(f"Health check failed for {server}: {e}")
        return healthy_servers

class TicTacToeLoadBalancer:
    """HTTP Load Balancer for TicTacToe servers"""
    
    def __init__(self, host='0.0.0.0', port=44444, max_workers=20):
        self.host = host
        self.port = port
        self.max_workers = max_workers
        self.backend_list = BackendServerList()
        self.running = False
        
        # Create main socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
    def proxy_data(self, source_sock, dest_sock, direction):
        """Proxy data between client and backend server"""
        try:
            while True:
                try:
                    # Receive data from source
                    data = source_sock.recv(4096)
                    if not data:
                        break
                        
                    # Send data to destination
                    dest_sock.sendall(data)
                    logging.debug(f"Proxied {len(data)} bytes {direction}")
                    
                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    break
                    
        except Exception as e:
            logging.error(f"Error in proxy_data ({direction}): {e}")
        finally:
            try:
                source_sock.close()
                dest_sock.close()
            except:
                pass
    
    def handle_client_connection(self, client_socket, client_address):
        """Handle a single client connection"""
        backend_socket = None
        try:
            # Get backend server
            backend_address = self.backend_list.get_server()
            
            # Create connection to backend
            backend_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            backend_socket.settimeout(10)
            
            logging.info(f"Client {client_address} connecting to backend {backend_address}")
            
            # Connect to backend server
            backend_socket.connect(backend_address)
            
            # Set timeouts
            client_socket.settimeout(30)
            backend_socket.settimeout(30)
            
            # Create threads for bidirectional data transfer
            client_to_backend = threading.Thread(
                target=self.proxy_data,
                args=(client_socket, backend_socket, "client->backend")
            )
            
            backend_to_client = threading.Thread(
                target=self.proxy_data,
                args=(backend_socket, client_socket, "backend->client")
            )
            
            # Start proxy threads
            client_to_backend.daemon = True
            backend_to_client.daemon = True
            
            client_to_backend.start()
            backend_to_client.start()
            
            # Wait for threads to complete
            client_to_backend.join()
            backend_to_client.join()
            
        except socket.timeout:
            logging.warning(f"Connection timeout for client {client_address}")
        except ConnectionRefusedError:
            logging.error(f"Backend server {backend_address} refused connection")
            self.send_error_response(client_socket, 503, "Service Unavailable")
        except Exception as e:
            logging.error(f"Error handling client {client_address}: {e}")
            self.send_error_response(client_socket, 500, "Internal Server Error")
        finally:
            try:
                client_socket.close()
                if backend_socket:
                    backend_socket.close()
            except:
                pass
    
    def send_error_response(self, client_socket, status_code, status_message):
        """Send HTTP error response to client"""
        try:
            error_body = f'{{"status": "ERROR", "message": "{status_message}"}}'
            response = (
                f"HTTP/1.1 {status_code} {status_message}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(error_body)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
                f"{error_body}"
            )
            client_socket.sendall(response.encode('utf-8'))
        except:
            pass
    
    def health_check_loop(self):
        """Periodic health check of backend servers"""
        while self.running:
            try:
                healthy_servers = self.backend_list.health_check()
                if len(healthy_servers) == 0:
                    logging.critical("No healthy backend servers available!")
                else:
                    logging.info(f"Healthy servers: {len(healthy_servers)}/{len(self.backend_list.servers)}")
                
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logging.error(f"Error in health check loop: {e}")
    
    def start_server(self):
        """Start the load balancer server"""
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(10)
            self.running = True
            
            logging.info(f"TicTacToe Load Balancer started on {self.host}:{self.port}")
            logging.info(f"Backend servers: {self.backend_list.servers}")
            logging.info(f"Max workers: {self.max_workers}")
            
            # Start health check thread
            health_thread = threading.Thread(target=self.health_check_loop)
            health_thread.daemon = True
            health_thread.start()
            
            # Use ThreadPoolExecutor to handle multiple connections
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                active_connections = []
                
                while self.running:
                    try:
                        client_socket, client_address = self.socket.accept()
                        logging.info(f"New connection from {client_address}")
                        
                        # Submit connection handling to thread pool
                        future = executor.submit(
                            self.handle_client_connection,
                            client_socket,
                            client_address
                        )
                        active_connections.append(future)
                        
                        # Clean up completed futures
                        active_connections = [f for f in active_connections if not f.done()]
                        
                        # Log active connections count
                        if len(active_connections) % 10 == 0:
                            logging.info(f"Active connections: {len(active_connections)}")
                            
                    except socket.error as e:
                        if self.running:
                            logging.error(f"Socket error: {e}")
                        break
                    except Exception as e:
                        logging.error(f"Error accepting connection: {e}")
                        break
                        
        except Exception as e:
            logging.error(f"Error starting load balancer: {e}")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Gracefully shutdown the load balancer"""
        if not self.running:
            return
            
        logging.info("Shutting down load balancer...")
        self.running = False
        
        try:
            self.socket.close()
        except:
            pass
            
        logging.info("Load balancer shutdown complete")

def main():
    """Main function to run the load balancer"""
    load_balancer = TicTacToeLoadBalancer()
    
    try:
        load_balancer.start_server()
    except KeyboardInterrupt:
        logging.info("Received interrupt signal...")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
    finally:
        load_balancer.shutdown()

if __name__ == "__main__":
    main()