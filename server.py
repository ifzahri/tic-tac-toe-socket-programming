import socket
import threading
import json
import logging
import uuid
from datetime import datetime

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
        )  # game_id: {'board': [], 'players': [], 'current_turn': 0, 'status': 'waiting/playing/finished', 'winner': None}
        self.players = {}  # player_id: {'game_id': None, 'symbol': 'X' or 'O'}
        self.game_history = {}
        self.next_game_id = 1

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

            if method == "POST" and path.startswith("/player/"):
                player_id = path.split("/")[-1]
                result = self.register_player(player_id)
            elif method == "GET" and path == "/games":
                result = self.get_available_games()
            elif method == "GET" and path.startswith("/history/"):
                player_id = path.split("/")[-1]
                result = self.get_player_history(player_id)
            elif method == "POST" and path.startswith("/game/create/"):
                player_id = path.split("/")[-1]
                result = self.create_game(player_id)
            elif method == "POST" and path.startswith("/game/join/"):
                player_id = path.split("/")[-1]
                data = json.loads(body)
                game_id = data.get("game_id")
                result = self.join_game(player_id, game_id)
            elif method == "POST" and path.startswith("/move/"):
                player_id = path.split("/")[-1]
                data = json.loads(body)
                result = self.make_move(player_id, data["row"], data["col"])
            elif method == "GET" and path.startswith("/game/state/"):
                player_id = path.split("/")[-1]
                result = self.get_game_state(player_id)
            elif method == "POST" and path.startswith("/game/leave/"):
                player_id = path.split("/")[-1]
                result = self.leave_game(player_id)

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

    def register_player(self, player_id):
        if not player_id:
            return {"status": "ERROR", "message": "Player ID required"}
        if player_id not in self.players:
            self.players[player_id] = {"game_id": None, "symbol": None}
        return {"status": "OK", "message": "Player registered", "player_id": player_id}

    def create_game(self, player_id):
        if player_id not in self.players or self.players[player_id].get("game_id"):
            return {
                "status": "ERROR",
                "message": "Player not registered or already in a game",
            }
        game_id = str(uuid.uuid4().hex[:4])
        self.games[game_id] = {
            "board": [["." for _ in range(3)] for _ in range(3)],
            "players": [player_id],
            "current_turn_idx": 0,
            "status": "waiting",
            "winner": None,
            "symbols": {player_id: "X"},
        }
        self.players[player_id]["game_id"] = game_id
        self.players[player_id]["symbol"] = "X"
        return {"status": "OK", "message": "Game created", "game_id": game_id}

    def join_game(self, player_id, game_id):
        if player_id not in self.players or self.players[player_id].get("game_id"):
            return {
                "status": "ERROR",
                "message": "Player not registered or already in a game",
            }
        if game_id not in self.games or self.games[game_id]["status"] != "waiting":
            return {"status": "ERROR", "message": "Game not available for joining"}
        game = self.games[game_id]
        if len(game["players"]) >= 2:
            return {"status": "ERROR", "message": "Game is already full"}

        game["players"].append(player_id)
        game["status"] = "playing"
        game["symbols"][player_id] = "O"
        self.players[player_id]["game_id"] = game_id
        self.players[player_id]["symbol"] = "O"
        return {
            "status": "OK",
            "message": "Joined game",
            **self.get_game_state(player_id),
        }

    def get_available_games(self):
        available = [
            {"game_id": gid, "created_by": g["players"][0]}
            for gid, g in self.games.items()
            if g["status"] == "waiting"
        ]
        return {"status": "OK", "available_games": available}

    def get_game_state(self, player_id):
        if player_id not in self.players:
            return {"status": "ERROR", "message": "Invalid player ID"}
        game_id = self.players[player_id].get("game_id")
        if not game_id or game_id not in self.games:
            return {"status": "ERROR", "message": "Player not in a game"}
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
                "your_symbol": self.players[player_id].get("symbol"),
                "players": game["players"],
                "symbols": game["symbols"],
            },
        }

    def make_move(self, player_id, row, col):
        if player_id not in self.players:
            return {"status": "ERROR", "message": "Invalid player ID"}
        game_id = self.players[player_id].get("game_id")
        if not game_id:
            return {"status": "ERROR", "message": "Player not in a game"}

        game = self.games[game_id]
        if game["status"] != "playing":
            return {"status": "ERROR", "message": "Game not in progress"}
        if game["players"][game["current_turn_idx"]] != player_id:
            return {"status": "ERROR", "message": "Not your turn"}
        if not (0 <= row < 3 and 0 <= col < 3 and game["board"][row][col] == "."):
            return {"status": "ERROR", "message": "Invalid move"}

        symbol = self.players[player_id]["symbol"]
        game["board"][row][col] = symbol

        if self.check_winner(game["board"], symbol):
            self._end_game_and_record_history(game_id, symbol, reason="win")
        elif self.is_board_full(game["board"]):
            self._end_game_and_record_history(game_id, "draw", reason="draw")
        else:
            game["current_turn_idx"] = 1 - game["current_turn_idx"]

        return {
            "status": "OK",
            "message": "Move made",
            **self.get_game_state(player_id),
        }

    def check_winner(self, board, symbol):
        # Check rows, columns, and diagonals for the given symbol
        for i in range(3):
            if all(board[i][j] == symbol for j in range(3)):
                return True
            if all(board[j][i] == symbol for j in range(3)):
                return True
        if board[0][0] == board[1][1] == board[2][2] == symbol:
            return True
        if board[0][2] == board[1][1] == board[2][0] == symbol:
            return True
        return False

    def is_board_full(self, board):
        return all(cell != "." for row in board for cell in row)

    def _end_game_and_record_history(self, game_id, winner_symbol, reason="completed"):
        game = self.games.get(game_id)
        if not game:
            return

        game["status"] = "finished"
        game["winner"] = winner_symbol

        history_entry = {
            "game_id": game_id,
            "players": list(game["players"]),
            "winner": winner_symbol,
            "date": datetime.utcnow().isoformat(),
            "symbols": dict(game["symbols"]),
            "reason": reason,
        }

        for p_id in game["players"]:
            if p_id not in self.game_history:
                self.game_history[p_id] = []
            self.game_history[p_id].append(history_entry)
            if p_id in self.players:
                self.players[p_id]["game_id"] = None
                self.players[p_id]["symbol"] = None

    def get_player_history(self, player_id):
        if player_id not in self.players:
            return {"status": "ERROR", "message": "Player not registered."}

        # Add symbols to history entries for client-side display logic
        history_with_symbols = []
        for entry in self.game_history.get(player_id, []):
            game_id = entry["game_id"]
            if game_id in self.games:
                entry["symbols"] = self.games[game_id].get("symbols", {})
            history_with_symbols.append(entry)

        return {"status": "OK", "history": self.game_history.get(player_id, [])}

    def leave_game(self, player_id):
        if player_id not in self.players:
            return {"status": "ERROR", "message": "Invalid player ID."}
        game_id = self.players[player_id].get("game_id")
        if game_id and game_id in self.games:
            game = self.games[game_id]
            if game["status"] != "finished" and len(game["players"]) > 1:
                other_player = next(
                    (p for p in game["players"] if p != player_id), None
                )
                if other_player:
                    winner_symbol = game["symbols"].get(other_player)
                    self._end_game_and_record_history(
                        game_id, winner_symbol, reason="disconnect"
                    )
            elif game["status"] == "waiting":
                del self.games[game_id]

        self.players[player_id]["game_id"] = None
        self.players[player_id]["symbol"] = None
        return {"status": "OK", "message": "You have left the game."}


if __name__ == "__main__":
    server = TicTacToeHttpServer()
    try:
        server.start_server()
    except KeyboardInterrupt:
        logging.info("Server shutting down...")
        server.socket.close()
        logging.info("Server closed.")