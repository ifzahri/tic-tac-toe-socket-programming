import json
import logging
from datetime import datetime
from game_logic import GameLogic 

class HttpServer:
    def __init__(self):
        self.logic = GameLogic()

    def response(self, status_code, status_message, body_dict):
        body_bytes = json.dumps(body_dict).encode('utf-8')
        tanggal = datetime.now().strftime('%c')
        headers = [
            f"HTTP/1.1 {status_code} {status_message}",
            f"Date: {tanggal}",
            "Server: TicTacToe/1.0",
            f"Content-Length: {len(body_bytes)}",
            "Content-Type: application/json",
            "Connection: close",
            "\r\n"
        ]
        response_str = "\r\n".join(headers)
        return response_str.encode('utf-8') + body_bytes

    def parse_request(self, request_data):
        lines = request_data.split('\r\n')
        request_line = lines[0]
        try:
            method, path, _ = request_line.split(" ")
        except ValueError:
            return None, None, None
        
        body = ""
        if '\r\n\r\n' in request_data:
            body = request_data.split('\r\n\r\n', 1)[1]
        
        return method, path, body

    def proses(self, request_data):
        method, path, body = self.parse_request(request_data)

        if method is None:
            return self.response(400, "Bad Request", {"status": "ERROR", "message": "Malformed request line"})

        logging.info(f"Request: {method} {path}")

        parts = path.strip("/").split("/")
        player_id_from_path = None
        if len(parts) > 1:
            potential_id = parts[-1]
            if potential_id in self.logic.players:
                player_id_from_path = potential_id
        
        if player_id_from_path:
            self.logic.update_player_last_seen(player_id_from_path)
        
        response_body = None
        try:
            if method == "POST" and path.startswith("/player/"):
                player_id = path.split("/")[-1]
                response_body = self.logic.register_player(player_id)
            elif method == "GET" and path == "/games":
                response_body = self.logic.get_available_games()
            elif method == "GET" and path.startswith("/history/"):
                player_id = path.split("/")[-1]
                response_body = self.logic.get_player_history(player_id)
            elif method == "POST" and path.startswith("/game/create/"):
                player_id = path.split("/")[-1]
                response_body = self.logic.create_game(player_id)
            elif method == "POST" and path.startswith("/game/join/"):
                player_id = path.split("/")[-1]
                data = json.loads(body) if body else {}
                response_body = self.logic.join_game(player_id, data.get("game_id"))
            elif method == "POST" and path.startswith("/game/spectate/"):
                player_id = path.split("/")[-1]
                data = json.loads(body) if body else {}
                response_body = self.logic.spectate_game(player_id, data.get("game_id"))
            elif method == "POST" and path.startswith("/move/"):
                player_id = path.split("/")[-1]
                data = json.loads(body) if body else {}
                response_body = self.logic.make_move(player_id, data.get("row"), data.get("col"))
            elif method == "GET" and path.startswith("/game/state/"):
                player_id = path.split("/")[-1]
                response_body = self.logic.get_game_state(player_id)
            elif method == "POST" and path.startswith("/game/leave/"):
                player_id = path.split("/")[-1]
                response_body = self.logic.leave_game(player_id)
        
        except (json.JSONDecodeError, KeyError) as e:
             return self.response(400, "Bad Request", {"status": "ERROR", "message": f"Invalid JSON or missing key: {e}"})

        if response_body:
            return self.response(200, "OK", response_body)
        else:
            return self.response(404, "Not Found", {"status": "ERROR", "message": "Endpoint not found"})