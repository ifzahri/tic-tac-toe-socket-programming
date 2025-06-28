import socket
import threading
import json
import logging
import uuid
from datetime import datetime
import hashlib

logging.basicConfig(level=logging.INFO)


class TicTacToeHttpServer:
    def __init__(self, host="localhost", port=55556):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Game state
        self.games = (
            {}
        )  # game_id: {'board': [], 'players': [], 'spectators': [], 'current_turn': 0, 'status': 'waiting/playing/finished', 'winner': None, 'disconnected_players': []}
        self.users = {}  # username: {'password_hash': '', 'game_id': None, 'symbol': 'X' or 'O', 'last_seen': None, 'connected': False}
        self.game_history = {}
        self.load_users()

        # Lock for thread-safe access to shared game state
        self.lock = threading.Lock()

    def start_server(self):
        self.socket.bind((self.host, self.port))
        self.socket.listen(5)
        logging.info(f"Tic Tac Toe HTTP Server started on {self.host}:{self.port}")

        while True:
            client_socket, address = self.socket.accept()
            logging.info(f"Connection from {address}")
            client_thread = threading.Thread(
                target=self.handle_request, args=(client_socket,)
            )
            client_thread.daemon = True
            client_thread.start()

    def handle_request(self, client_socket):
        try:
            request_data = client_socket.recv(4096).decode("utf-8")
            if not request_data:
                return

            response = self.process_request(request_data)
        except Exception as e:
            logging.error(f"Error handling request: {e}")
            response = self.create_response(
                500, "Internal Server Error", {"status": "ERROR", "message": str(e)}
            )
        finally:
            client_socket.sendall(response)
            client_socket.close()

    def process_request(self, request_data):
        lines = request_data.split("\r\n")
        request_line = lines[0]

        try:
            method, path, _ = request_line.split(" ")
        except ValueError:
            return self.create_response(
                400,
                "Bad Request",
                {"status": "ERROR", "message": "Malformed request line"},
            )

        logging.info(f"Request: {method} {path}")

        body = ""
        # Find the body by locating the double CRLF, which separates headers from the body.
        if "\r\n\r\n" in request_data:
            body = request_data.split("\r\n\r\n", 1)[1]

        # Routing
        with self.lock:
            # Default result for unhandled paths
            result = self.create_response(
                404, "Not Found", {"status": "ERROR", "message": "Endpoint not found"}
            )

            if method == "POST" and path == "/register":
                data = json.loads(body)
                result = self.register_user(data.get('username'), data.get('password'))
            elif method == "POST" and path == "/login":
                data = json.loads(body)
                result = self.login_user(data.get('username'), data.get('password'))
            elif method == "GET" and path == "/games":
                result = self.get_available_games()
            elif method == "GET" and path.startswith("/history/"):
                username = path.split("/")[-1]
                result = self.get_player_history(username)
            elif method == "POST" and path.startswith("/game/create/"):
                username = path.split("/")[-1]
                result = self.create_game(username)
            elif method == "POST" and path.startswith("/game/join/"):
                username = path.split("/")[-1]
                data = json.loads(body)
                game_id = data.get("game_id")
                result = self.join_game(username, game_id)
            elif method == "POST" and path.startswith("/game/spectate/"):
                username = path.split("/")[-1]
                data = json.loads(body)
                game_id = data.get("game_id")
                result = self.spectate_game(username, game_id)
            elif method == "POST" and path.startswith("/move/"):
                username = path.split("/")[-1]
                data = json.loads(body)
                result = self.make_move(username, data["row"], data["col"])
            elif method == "GET" and path.startswith("/game/state/"):
                username = path.split("/")[-1]
                result = self.get_game_state(username)
            elif method == "POST" and path.startswith("/game/leave/"):
                username = path.split("/")[-1]
                result = self.leave_game(username)
            elif method == "POST" and path.startswith("/disconnect/"):
                username = path.split("/")[-1]
                result = self.disconnect_user(username)

            # Check if result is a dictionary to be formatted as a response
            if isinstance(result, dict):
                return self.create_response(200, "OK", result)
            return result  # If result is already a full HTTP response

    def create_response(self, status_code, status_message, body_dict):
        body_bytes = json.dumps(body_dict).encode("utf-8")
        tanggal = datetime.now().strftime("%c")
        headers = [
            f"HTTP/1.1 {status_code} {status_message}",
            f"Date: {tanggal}",
            "Server: TicTacToe/1.0",
            f"Content-Length: {len(body_bytes)}",
            "Content-Type: application/json",
            "Connection: close",
            "\r\n",
        ]
        response_str = "\r\n".join(headers)
        return response_str.encode("utf-8") + body_bytes

    def _hash_password(self, password):
        # Storing password in plain text as requested by user.
        return password

    def save_users(self):
        with open('users.json', 'w') as f:
            json.dump(self.users, f, indent=4)

    def load_users(self):
        try:
            with open('users.json', 'r') as f:
                self.users = json.load(f)
                logging.info("User data loaded.")
        except (FileNotFoundError, json.JSONDecodeError):
            logging.info("No user data found, starting fresh.")
            self.users = {}

    def register_user(self, username, password):
        if not username or not password:
            return {"status": "ERROR", "message": "Username and password are required"}
        if username in self.users:
            return {"status": "ERROR", "message": "Username already exists"}
        
        self.users[username] = {
            "password": self._hash_password(password),
            "game_id": None, 
            "symbol": None, 
            "last_seen": None, 
            "connected": False
        }
        self.save_users()
        return {"status": "OK", "message": "User registered successfully"}

    def login_user(self, username, password):
        if username not in self.users:
            return {"status": "ERROR", "message": "Username not found"}
        
        user = self.users[username]
        if user['password'] != self._hash_password(password):
            return {"status": "ERROR", "message": "Invalid password"}
        
        if user.get('connected'):
            return {"status": "ERROR", "message": "User is already logged in elsewhere"}

        user['connected'] = True
        user['last_seen'] = datetime.now().isoformat()
        self.save_users()

        game_id = user.get('game_id')
        if game_id and game_id in self.games:
            game = self.games[game_id]
            if username in game.get('disconnected_players', []):
                game['disconnected_players'].remove(username)
                if not game['disconnected_players']:
                    game['status'] = 'playing'
                
                return {
                    "status": "OK",
                    "message": "Reconnected to game.",
                    "game_state": self.get_game_state(username).get('game_state')
                }
        
        return {"status": "OK", "message": "Login successful. No active game found."}


    def create_game(self, username):
        if username not in self.users or self.users[username].get("game_id"):
            return {
                "status": "ERROR",
                "message": "User not registered or already in a game",
            }
        game_id = str(uuid.uuid4().hex[:4])
        self.games[game_id] = {
            "board": [["." for _ in range(3)] for _ in range(3)],
            "players": [username],
            "spectators": [],
            "current_turn_idx": 0,
            "status": "waiting",
            "winner": None,
            "symbols": {username: "X"},
            "disconnected_players": [],
        }
        self.users[username]["game_id"] = game_id
        self.users[username]["symbol"] = "O" # Creator is now Circle
        return {"status": "OK", "message": "Game created", "game_id": game_id}

    def join_game(self, username, game_id):
        if username not in self.users or self.users[username].get("game_id"):
            return {
                "status": "ERROR",
                "message": "User not registered or already in a game",
            }
        if game_id not in self.games or self.games[game_id]["status"] != "waiting":
            return {"status": "ERROR", "message": "Game not available for joining"}
        game = self.games[game_id]
        if len(game["players"]) >= 2:
            return {"status": "ERROR", "message": "Game is already full"}

        game["players"].append(username)
        game["status"] = "playing"
        game["symbols"][username] = "X" # Joiner is now Cross
        self.users[username]["game_id"] = game_id
        self.users[username]["symbol"] = "X"
        return {
            "status": "OK",
            "message": "Joined game",
            **self.get_game_state(username),
        }

    def spectate_game(self, username, game_id):
        if username not in self.users or self.users[username].get("game_id"):
            return {"status": "ERROR", "message": "User not registered or already in a game"}
        if game_id not in self.games:
            return {"status": "ERROR", "message": "Game does not exist"}
        game = self.games[game_id]
        if game['status'] not in ['playing', 'finished']:
            return {"status": "ERROR", "message": "Game not available for spectating"}

        game["spectators"].append(username)
        self.users[username]["game_id"] = game_id
        # Spectators have no symbol
        self.users[username]["symbol"] = None

        return {
            "status": "OK",
            "message": "Now spectating game",
            **self.get_game_state(username),
        }


    def get_available_games(self):
        available = [
            {"game_id": gid, "created_by": g["players"][0], "status": g["status"]}
            for gid, g in self.games.items()
            if g["status"] in ["waiting", "playing"]
        ]
        return {"status": "OK", "available_games": available}

    def get_game_state(self, username):
        if username not in self.users:
            return {"status": "ERROR", "message": "Invalid username"}
        game_id = self.users[username].get("game_id")
        if not game_id or game_id not in self.games:
            return {"status": "ERROR", "message": "User not in a game"}
        game = self.games[game_id]
        current_player = (
            game["players"][game["current_turn_idx"]]
            if game["status"] == "playing"
            else None
        )
        return {
            "status": "OK",
            "game_state": {
                "board": game["board"],
                "game_status": game["status"],
                "current_turn": current_player,
                "winner": game["winner"],
                "your_symbol": self.users[username].get("symbol"),
                "players": game["players"],
                "symbols": game["symbols"],
                "disconnected_players": game.get("disconnected_players", []),
            },
        }

    def make_move(self, username, row, col):
        if username not in self.users:
            return {"status": "ERROR", "message": "Invalid username"}
        game_id = self.users[username].get("game_id")
        if not game_id:
            return {"status": "ERROR", "message": "User not in a game"}

        game = self.games[game_id]
        if game["status"] != "playing":
            return {"status": "ERROR", "message": "Game not in progress"}
        if game["players"][game["current_turn_idx"]] != username:
            return {"status": "ERROR", "message": "Not your turn"}
        if not (0 <= row < 3 and 0 <= col < 3 and game["board"][row][col] == "."):
            return {"status": "ERROR", "message": "Invalid move"}

        symbol = self.users[username]["symbol"]
        game["board"][row][col] = symbol

        winner = self.check_winner(game["board"])
        if winner:
            winning_username = next((uid for uid, sym in game["symbols"].items() if sym == winner), None)
            self._end_game_and_record_history(game_id, winning_username, reason="win")
        elif self.is_board_full(game["board"]):
            self._end_game_and_record_history(game_id, "draw", reason="draw")
        else:
            game["current_turn_idx"] = 1 - game["current_turn_idx"]

        return {
            "status": "OK",
            "message": "Move made",
            **self.get_game_state(username),
        }

    def check_winner(self, board):
        for symbol in ["X", "O"]:
            for i in range(3):
                if all(board[i][j] == symbol for j in range(3)): return symbol
                if all(board[j][i] == symbol for j in range(3)): return symbol
            if board[0][0] == board[1][1] == board[2][2] == symbol: return symbol
            if board[0][2] == board[1][1] == board[2][0] == symbol: return symbol
        return None

    def is_board_full(self, board):
        return all(cell != "." for row in board for cell in row)

    def _end_game_and_record_history(self, game_id, winner_id, reason="completed"):
        game = self.games.get(game_id)
        if not game:
            return

        game["status"] = "finished"
        game["winner"] = winner_id

        history_entry = {
            "game_id": game_id,
            "players": list(game["players"]),
            "winner": winner_id,
            "date": datetime.utcnow().isoformat(),
            "symbols": dict(game["symbols"]),
            "reason": reason,
        }
        
        all_involved_users = game["players"] + game["spectators"]
        for username in all_involved_users:
            if username not in self.game_history:
                self.game_history[username] = []
            self.game_history[username].append(history_entry)
            if username in self.users:
                self.users[username]["game_id"] = None
                self.users[username]["symbol"] = None


    def get_player_history(self, username):
        if username not in self.users:
            return {"status": "ERROR", "message": "User not registered."}

        return {"status": "OK", "history": self.game_history.get(username, [])}

    def leave_game(self, username):
        # This is now for explicitly leaving, not just disconnecting
        if username not in self.users:
            return {"status": "ERROR", "message": "Invalid username."}
        
        game_id = self.users[username].get("game_id")
        if game_id and game_id in self.games:
            game = self.games[game_id]
            if username in game["players"]:
                if game["status"] != "finished":
                    other_player = next((p for p in game["players"] if p != username), None)
                    if other_player:
                        self._end_game_and_record_history(game_id, other_player, reason="abandon")
                # If only one player or waiting, just remove the game
                elif len(game["players"]) == 1:
                     del self.games[game_id]

            elif username in game["spectators"]:
                game["spectators"].remove(username)

        # Reset user's game state
        self.users[username]["game_id"] = None
        self.users[username]["symbol"] = None
        self.users[username]['connected'] = False
        self.save_users() # Ensure state is saved
        return {"status": "OK", "message": "You have left the game."}

    def disconnect_user(self, username):
        if username in self.users:
            user = self.users[username]
            user['connected'] = False
            user['last_seen'] = datetime.now().isoformat()
            
            game_id = user.get('game_id')
            if game_id and game_id in self.games:
                game = self.games[game_id]
                if username in game['players'] and username not in game.get('disconnected_players', []):
                    game.setdefault('disconnected_players', []).append(username)
                    if game['status'] == 'playing':
                        game['status'] = 'disconnected'
            self.save_users()
        return {"status": "OK", "message": "User disconnected"}


if __name__ == "__main__":
    server = TicTacToeHttpServer()
    try:
        server.start_server()
    except KeyboardInterrupt:
        logging.info("Server shutting down...")
        server.socket.close()
        logging.info("Server closed.")
