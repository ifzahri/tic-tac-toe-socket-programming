import json
import logging
import uuid
from datetime import datetime, timedelta
import os

logging.basicConfig(level=logging.INFO)

class HttpHandler:
    def __init__(self, state_file="game_state.json"):
        self.state_file = state_file
        self.offline_threshold = timedelta(seconds=10)
        
        # Game state
        self.games = {}
        self.players = {}
        self.game_history = {}
        self.load_game_state()

    def load_game_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    state = json.load(f)
                    self.games = state.get("games", {})
                    self.players = state.get("players", {})
                    # Convert string timestamps back to datetime objects
                    for pid, pdata in self.players.items():
                        if "last_seen" in pdata and isinstance(pdata["last_seen"], str):
                            # Use fromisoformat for more robust parsing
                            try:
                                pdata["last_seen"] = datetime.fromisoformat(pdata["last_seen"])
                            except ValueError:
                                # Fallback for older format if necessary
                                iso_date_str = pdata["last_seen"].split(".")[0]
                                pdata["last_seen"] = datetime.strptime(iso_date_str, "%Y-%m-%dT%H:%M:%S")
                        
                        if "connection_status" not in pdata:
                            pdata["connection_status"] = "offline"

                    self.game_history = state.get("game_history", {})
                    logging.info("Game state loaded from file.")
            except (json.JSONDecodeError, IOError, ValueError) as e:
                logging.error(f"Could not load game state: {e}. Starting fresh.")
                self.games = {}
                self.players = {}
                self.game_history = {}

    def save_game_state(self):
        players_copy = {}
        for pid, pdata in self.players.items():
            players_copy[pid] = pdata.copy()
            if "last_seen" in players_copy[pid] and isinstance(
                players_copy[pid]["last_seen"], datetime
            ):
                players_copy[pid]["last_seen"] = players_copy[pid][
                    "last_seen"
                ].isoformat()

        state = {
            "games": self.games,
            "players": players_copy,
            "game_history": self.game_history,
        }
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=4)
        logging.info("Game state saved.")

    def update_player_last_seen(self, player_id):
        if player_id in self.players:
            self.players[player_id]["last_seen"] = datetime.utcnow()
            # If player was offline, mark them as online and save state
            if self.players[player_id].get("connection_status") == "offline":
                logging.info(f"Player {player_id} has reconnected and is now online.")
                self.players[player_id]["connection_status"] = "online"
                self.save_game_state()

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

    def parse_request(self, request_data):
        lines = request_data.split("\r\n")
        request_line = lines[0]
        
        try:
            method, path, _ = request_line.split(" ")
        except ValueError:
            return None, None, None
        
        body = ""
        if "\r\n\r\n" in request_data:
            body = request_data.split("\r\n\r\n", 1)[1]
        
        return method, path, body

    def process_request(self, request_data):
        method, path, body = self.parse_request(request_data)
        
        if method is None:
            return self.create_response(
                400,
                "Bad Request",
                {"status": "ERROR", "message": "Malformed request line"},
            )

        logging.info(f"Request: {method} {path}")

        parts = path.strip("/").split("/")
        player_id_from_path = None
        if len(parts) > 1:
            # A more robust way to find the player ID in the path
            potential_id = parts[-1] or (len(parts) > 2 and parts[-2])
            if potential_id in self.players:
                player_id_from_path = potential_id
        
        if player_id_from_path:
            self.update_player_last_seen(player_id_from_path)
        
        result = self.create_response(404, "Not Found", {"status": "ERROR", "message": "Endpoint not found"})
        
        # Routing
        try:
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
                data = json.loads(body) if body else {}
                result = self.join_game(player_id, data.get("game_id"))
            elif method == "POST" and path.startswith("/game/spectate/"):
                player_id = path.split("/")[-1]
                data = json.loads(body) if body else {}
                result = self.spectate_game(player_id, data.get("game_id"))
            elif method == "POST" and path.startswith("/move/"):
                player_id = path.split("/")[-1]
                data = json.loads(body) if body else {}
                result = self.make_move(player_id, data.get("row"), data.get("col"))
            elif method == "GET" and path.startswith("/game/state/"):
                player_id = path.split("/")[-1]
                result = self.get_game_state(player_id)
            elif method == "POST" and path.startswith("/game/leave/"):
                player_id = path.split("/")[-1]
                result = self.leave_game(player_id)
        except (json.JSONDecodeError, KeyError) as e:
             result = self.create_response(400, "Bad Request", {"status": "ERROR", "message": f"Invalid JSON or missing key: {e}"})

        if isinstance(result, dict):
            return self.create_response(200, "OK", result)
        return result

    def register_player(self, player_id):
        if not player_id:
            return {"status": "ERROR", "message": "Player ID required"}
        if player_id not in self.players:
            self.players[player_id] = {
                "game_id": None,
                "symbol": None,
                "last_seen": datetime.utcnow(),
                "connection_status": "online",
            }
        else:
            self.players[player_id]["last_seen"] = datetime.utcnow()
            self.players[player_id]["connection_status"] = "online"
        self.save_game_state()
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
            "spectators": [],
            "current_turn_idx": 0,
            "status": "waiting",
            "winner": None,
            "symbols": {player_id: "X"},
        }
        self.players[player_id]["game_id"] = game_id
        self.players[player_id]["symbol"] = "X"
        self.save_game_state()
        return {"status": "OK", "message": "Game created", "game_id": game_id}

    def join_game(self, player_id, game_id):
        if player_id not in self.players or self.players[player_id].get("game_id"):
            return { "status": "ERROR", "message": "Player not registered or already in a game" }
        if not game_id or game_id not in self.games or self.games[game_id]["status"] != "waiting":
            return {"status": "ERROR", "message": "Game not available for joining"}
        game = self.games[game_id]
        if len(game["players"]) >= 2:
            return {"status": "ERROR", "message": "Game is already full"}

        game["players"].append(player_id)
        game["status"] = "playing"
        game["symbols"][player_id] = "O"
        self.players[player_id]["game_id"] = game_id
        self.players[player_id]["symbol"] = "O"
        self.save_game_state()
        return {
            "status": "OK",
            "message": "Joined game",
            **self.get_game_state(player_id),
        }

    def spectate_game(self, player_id, game_id):
        if player_id not in self.players or self.players[player_id].get("game_id"):
            return { "status": "ERROR", "message": "Player not registered or already in a game" }
        if not game_id or game_id not in self.games:
            return {"status": "ERROR", "message": "Game does not exist"}
        
        game = self.games[game_id]
        game["spectators"].append(player_id)
        self.players[player_id]["game_id"] = game_id
        self.players[player_id]["symbol"] = None # Spectators have no symbol
        self.save_game_state()
        return {
            "status": "OK",
            "message": "Now spectating game",
            **self.get_game_state(player_id),
        }

    def get_available_games(self):
        available = [
            {"game_id": gid, "created_by": g["players"][0], "status": g["status"]}
            for gid, g in self.games.items()
            if g["status"] in ["waiting", "playing"]
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
            if game["status"] == "playing" and len(game["players"]) == 2
            else None
        )

        player_statuses = {
            p_id: self.players.get(p_id, {}).get("connection_status", "offline")
            for p_id in game["players"]
        }

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
                "player_statuses": player_statuses,
            },
        }

    def make_move(self, player_id, row, col):
        if player_id not in self.players:
            return {"status": "ERROR", "message": "Invalid player ID"}
        game_id = self.players[player_id].get("game_id")
        if not game_id or game_id not in self.games:
            return {"status": "ERROR", "message": "Player not in a game"}

        game = self.games[game_id]
        if game["status"] != "playing":
            return {"status": "ERROR", "message": "Game not in progress"}
        if game["players"][game["current_turn_idx"]] != player_id:
            return {"status": "ERROR", "message": "Not your turn"}
        if not (isinstance(row, int) and isinstance(col, int) and 0 <= row < 3 and 0 <= col < 3 and game["board"][row][col] == "."):
            return {"status": "ERROR", "message": "Invalid move"}

        symbol = self.players[player_id]["symbol"]
        game["board"][row][col] = symbol

        winner = self.check_winner(game["board"])
        if winner:
            winning_player_id = next((pid for pid, sym in game["symbols"].items() if sym == winner), None)
            self._end_game_and_record_history(game_id, winning_player_id, reason="win")
        elif self.is_board_full(game["board"]):
            self._end_game_and_record_history(game_id, "draw", reason="draw")
        else:
            game["current_turn_idx"] = 1 - game["current_turn_idx"]

        self.save_game_state()
        return {
            "status": "OK",
            "message": "Move made",
            **self.get_game_state(player_id),
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
        if not game or game["status"] == "finished": return

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

        all_involved_players = game["players"] + game["spectators"]
        for p_id in all_involved_players:
            if p_id not in self.game_history:
                self.game_history[p_id] = []
            self.game_history[p_id].append(history_entry)
            if p_id in self.players:
                self.players[p_id]["game_id"] = None
                self.players[p_id]["symbol"] = None
    
    def get_player_history(self, player_id):
        if player_id not in self.players:
            return {"status": "ERROR", "message": "Player not registered."}
        return {"status": "OK", "history": self.game_history.get(player_id, [])}

    def leave_game(self, player_id):
        if player_id not in self.players:
            return {"status": "ERROR", "message": "Invalid player ID."}
        game_id = self.players[player_id].get("game_id")

        if game_id and game_id in self.games:
            game = self.games[game_id]
            # If a player explicitly leaves, it's a forfeit. The other player wins.
            if player_id in game["players"] and game["status"] != "finished":
                if len(game["players"]) > 1:
                    other_player = next((p for p in game["players"] if p != player_id), None)
                    if other_player:
                        self._end_game_and_record_history(game_id, other_player, reason="forfeit")
                else:
                    # If they were the only one in a waiting game, just delete the game
                    del self.games[game_id]
            
            elif player_id in game["spectators"]:
                game["spectators"].remove(player_id)
                self.players[player_id]["game_id"] = None

        # This will run regardless, to clean up the player's state
        if player_id in self.players:
            self.players[player_id]["game_id"] = None
            self.players[player_id]["symbol"] = None

        self.save_game_state()
        return {"status": "OK", "message": "You have left the game."}

    def check_inactive_players(self):
        """
        MODIFIED: Checks for inactive players. If a player is inactive, they
        are marked as 'offline', but the game is NOT ended. It will wait for them.
        """
        now = datetime.utcnow()
        players_in_game = {
            pid: data
            for pid, data in self.players.items()
            if data.get("game_id")
        }
        state_changed = False

        for player_id, data in list(players_in_game.items()):
            last_seen = data.get("last_seen", now)
            
            # If player is inactive, just mark them as offline.
            # The game will be preserved, waiting for them to reconnect.
            if (
                now - last_seen > self.offline_threshold
                and data.get("connection_status") == "online"
            ):
                if player_id in self.players:
                    logging.info(f"Player {player_id} marked as offline due to inactivity.")
                    self.players[player_id]["connection_status"] = "offline"
                    state_changed = True

        if state_changed:
            self.save_game_state()