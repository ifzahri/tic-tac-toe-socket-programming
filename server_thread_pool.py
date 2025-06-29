import socket
import threading
import logging
import time
from concurrent.futures import ThreadPoolExecutor

# Impor kelas HttpServer dari file http.py
from http import HttpServer

logging.basicConfig(level=logging.INFO)


class ThreadPoolHTTPServer:
    def __init__(self, host="localhost", port=55556, max_workers=10):
        self.host = host
        self.port = port
        self.max_workers = max_workers
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.http_server = HttpServer()

        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.running = False

        self.lock = threading.Lock()

    def start_server(self):
        try:
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            self.running = True
            logging.info(
                f"Tic Tac Toe HTTP Server started on {self.host}:{self.port} with {self.max_workers} workers"
            )

            # Memulai thread untuk memeriksa pemain yang tidak aktif
            reaper_thread = threading.Thread(target=self.reap_inactive_players)
            reaper_thread.daemon = True
            reaper_thread.start()

            while self.running:
                try:
                    client_socket, address = self.socket.accept()
                    logging.info(f"Connection from {address}")

                    # Menangani request di thread pool
                    self.executor.submit(self.handle_request, client_socket)

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
        """Menangani request dari satu klien"""
        response = None
        try:
            client_socket.settimeout(30)
            request_data = client_socket.recv(4096).decode("utf-8")
            if not request_data:
                return

            # Menggunakan lock untuk memproses request secara thread-safe
            with self.lock:
                # Memanggil metode 'proses' dari HttpServer
                response = self.http_server.proses(request_data)

        except socket.timeout:
            logging.warning("Client request timed out")
            response = self.http_server.create_response(
                408,
                "Request Timeout",
                {"status": "ERROR", "message": "Request timeout"},
            )
        except Exception as e:
            logging.error(f"Error handling request: {e}")
            response = self.http_server.create_response(
                500, "Internal Server Error", {"status": "ERROR", "message": str(e)}
            )
        finally:
            if response:
                try:
                    # Mengirim response yang sudah lengkap (termasuk header)
                    client_socket.sendall(response)
                except Exception as e:
                    logging.error(f"Error sending response: {e}")
            client_socket.close()

    def reap_inactive_players(self):
        """Background thread untuk memeriksa pemain yang tidak aktif"""
        while self.running:
            try:
                time.sleep(5)
                with self.lock:
                    # Memanggil fungsi check_inactive_players dari game_logic melalui http_server
                    self.http_server.logic.check_inactive_players()
            except Exception as e:
                logging.error(f"Error in reaper thread: {e}")

    def shutdown(self):
        if not self.running:
            return

        logging.info("Shutting down server...")
        self.running = False

        try:
            with self.lock:
                self.http_server.logic.save_game_state()
        except Exception as e:
            logging.error(f"Error saving game state during shutdown: {e}")

        self.executor.shutdown(wait=True)
        
        try:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
                (self.host, self.port)
            )
        except:
            pass
        finally:
            self.socket.close()

        logging.info("Server shutdown complete.")


if __name__ == "__main__":
    server = ThreadPoolHTTPServer()
    try:
        server.start_server()
    except KeyboardInterrupt:
        logging.info("Received interrupt signal...")
    finally:
        server.shutdown()
