# File: lb.py (Versi dengan Logika Proxy yang Disederhanakan dan Lebih Stabil)

import socket
import time
import sys
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class BackendServerList:
    def __init__(self):
        self.all_servers = [('127.0.0.1', 55556), ('127.0.0.1', 55557), ('127.0.0.1', 55558)]
        self.healthy_servers = []
        self.current = 0
        self.lock = threading.Lock()
        
    def get_server(self):
        with self.lock:
            if not self.healthy_servers:
                return None
            server_count = len(self.healthy_servers)
            self.current = (self.current + 1) % server_count
            server = self.healthy_servers[self.current]
            logging.info(f"Selected healthy backend server: {server}")
            return server
    
    def update_health_status(self):
        live_servers = []
        for server in self.all_servers:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_sock:
                    test_sock.settimeout(1)
                    if test_sock.connect_ex(server) == 0:
                        live_servers.append(server)
            except Exception:
                pass
        with self.lock:
            if set(live_servers) != set(self.healthy_servers):
                 logging.info(f"Health status updated. Healthy servers: {len(live_servers)}/{len(self.all_servers)}")
            self.healthy_servers = live_servers

class TicTacToeLoadBalancer:
    def __init__(self, host='0.0.0.0', port=44444, max_workers=20):
        self.host = host
        self.port = port
        self.max_workers = max_workers
        self.backend_list = BackendServerList()
        self.running = False
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
    def handle_client_connection(self, client_socket, client_address):
        backend_socket = None
        try:
            backend_address = self.backend_list.get_server()
            if not backend_address:
                self.send_error_response(client_socket, 503, "Service Unavailable")
                return

            backend_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            backend_socket.settimeout(5)
            backend_socket.connect(backend_address)

            client_request = client_socket.recv(4096)
            if client_request:
                backend_socket.sendall(client_request)
            else:
                return

            while True:
                try:
                    backend_response = backend_socket.recv(4096)
                    if backend_response:
                        client_socket.sendall(backend_response)
                    else:
                        break
                except socket.timeout:
                    break

        except (socket.timeout, ConnectionRefusedError, ConnectionResetError) as e:
            logging.error(f"Failed to connect or proxy to backend: {e}")
            self.send_error_response(client_socket, 502, "Bad Gateway")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            self.send_error_response(client_socket, 500, "Internal Server Error")
        finally:
            if backend_socket:
                backend_socket.close()
            client_socket.close()
    
    def send_error_response(self, client_socket, status_code, status_message):
        try:
            error_body = f'{{"status": "ERROR", "message": "{status_message}"}}'
            response = ( f"HTTP/1.1 {status_code} {status_message}\r\n" f"Content-Type: application/json\r\n" f"Connection: close\r\n\r\n{error_body}" )
            client_socket.sendall(response.encode('utf-8'))
        except Exception:
            pass

    def health_check_loop(self):
        while self.running:
            try:
                self.backend_list.update_health_status()
                time.sleep(15)
            except Exception as e:
                logging.error(f"Error in health check loop: {e}")
    
    def start_server(self):
        self.socket.bind((self.host, self.port))
        self.socket.listen(100)
        self.running = True
        logging.info(f"TicTacToe Load Balancer (SIMPLE PROXY) started on {self.host}:{self.port}")
        
        health_thread = threading.Thread(target=self.health_check_loop)
        health_thread.daemon = True
        health_thread.start()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while self.running:
                try:
                    client_socket, client_address = self.socket.accept()
                    executor.submit(self.handle_client_connection, client_socket, client_address)
                except OSError:
                    break
    
    def shutdown(self):
        logging.info("Shutting down load balancer...")
        self.running = False
        try:
            self.socket.close()
        except:
            pass
        logging.info("Load balancer shutdown complete")


if __name__ == "__main__":
    load_balancer = TicTacToeLoadBalancer()
    try:
        load_balancer.start_server()
    except KeyboardInterrupt:
        load_balancer.shutdown()