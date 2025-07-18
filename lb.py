import socket
import time
import sys
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class BackendServerList:
    """Manages backend TicTacToe servers with round-robin selection and health checks"""
    
    def __init__(self):
        # Daftar master, tidak pernah berubah
        self.all_servers = [
            ('127.0.0.1', 55556),
            ('127.0.0.1', 55557),
            ('127.0.0.1', 55558),
        ]
        # Daftar server yang sehat, akan diperbarui oleh health check
        self.healthy_servers = list(self.all_servers)
        self.current = 0
        self.lock = threading.Lock()
        
    def get_server(self):
        """Get next HEALTHY server using round-robin algorithm"""
        with self.lock:
            if not self.healthy_servers:
                logging.critical("FATAL: No healthy backend servers available!")
                return None

            # Memilih dari daftar server yang sehat secara round-robin
            server_count = len(self.healthy_servers)
            self.current = (self.current + 1) % server_count
            server = self.healthy_servers[self.current]
            logging.info(f"Selected healthy backend server: {server}")
            return server
    
    def update_health_status(self):
        """Checks health of all servers and updates the healthy_servers list."""
        live_servers = []
        for server in self.all_servers:
            try:
                # Menggunakan context manager untuk memastikan socket tertutup
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_sock:
                    test_sock.settimeout(2) # Timeout 2 detik
                    if test_sock.connect_ex(server) == 0:
                        live_servers.append(server)
                    else:
                        logging.warning(f"Server {server} is unreachable")
            except Exception as e:
                logging.warning(f"Health check for {server} failed: {e}")
        
        with self.lock:
            # Hanya log jika ada perubahan status
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
        
    def proxy_data(self, source_sock, dest_sock):
        try:
            while self.running:
                data = source_sock.recv(4096)
                if not data: break
                dest_sock.sendall(data)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass # Kesalahan ini normal terjadi saat koneksi ditutup
        finally:
            source_sock.close()
            dest_sock.close()

    def handle_client_connection(self, client_socket, client_address):
        backend_socket = None
        try:
            backend_address = self.backend_list.get_server()
            if not backend_address:
                logging.error("No backend servers available to handle connection.")
                self.send_error_response(client_socket, 503, "Service Unavailable")
                return

            backend_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            backend_socket.connect(backend_address)
            
            # Memulai proxy dua arah dalam thread terpisah
            threading.Thread(target=self.proxy_data, args=(client_socket, backend_socket)).start()
            threading.Thread(target=self.proxy_data, args=(backend_socket, client_socket)).start()

        except ConnectionRefusedError:
            logging.error(f"Backend {backend_address} refused connection. Triggering health check.")
            self.backend_list.update_health_status() # Segera update jika koneksi ditolak
            self.send_error_response(client_socket, 503, "Service Unavailable")
        except Exception as e:
            logging.error(f"Error handling client {client_address}: {e}")
            self.send_error_response(client_socket, 500, "Internal Server Error")
        # Tidak ada 'finally' close di sini karena proxy_data yang akan menutup socket

    def send_error_response(self, client_socket, status_code, status_message):
        try:
            error_body = f'{{"status": "ERROR", "message": "{status_message}"}}'
            response = (
                f"HTTP/1.1 {status_code} {status_message}\r\n"
                f"Content-Type: application/json\r\n"
                f"Connection: close\r\n\r\n{error_body}"
            )
            client_socket.sendall(response.encode('utf-8'))
        except Exception:
            pass
        finally:
            client_socket.close()

    def health_check_loop(self):
        """Periodic health check of backend servers"""
        while self.running:
            try:
                self.backend_list.update_health_status()
                time.sleep(15)  # Check setiap 15 detik
            except Exception as e:
                logging.error(f"Error in health check loop: {e}")
    
    def start_server(self):
        self.socket.bind((self.host, self.port))
        self.socket.listen(100) # Menaikkan backlog
        self.running = True
        logging.info(f"TicTacToe Load Balancer started on {self.host}:{self.port}")
        
        health_thread = threading.Thread(target=self.health_check_loop)
        health_thread.daemon = True
        health_thread.start()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while self.running:
                try:
                    client_socket, client_address = self.socket.accept()
                    executor.submit(self.handle_client_connection, client_socket, client_address)
                except OSError: # Terjadi saat socket ditutup
                    break
    
    def shutdown(self):
        logging.info("Shutting down load balancer...")
        self.running = False
        self.socket.close()
        logging.info("Load balancer shutdown complete")

if __name__ == "__main__":
    load_balancer = TicTacToeLoadBalancer()
    try:
        load_balancer.start_server()
    except KeyboardInterrupt:
        load_balancer.shutdown()