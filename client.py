import datetime
import pygame
import sys
import socket
import json
import logging
import uuid
import time

logging.basicConfig(level=logging.INFO)


pygame.init()

WIDTH, HEIGHT = 600, 700
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Multiplayer Tic Tac Toe (HTTP)")

clock = pygame.time.Clock()
FPS = 30

# Colors & Fonts
WHITE, BLACK, BLUE, RED, GREEN, GRAY, LIGHT_GRAY, ORANGE, YELLOW = (
    (255, 255, 255),
    (0, 0, 0),
    (0, 100, 200),
    (200, 0, 0),
    (0, 200, 0),
    (128, 128, 128),
    (200, 200, 200),
    (255, 165, 0),
    (255, 255, 0),
)
font_large, font_medium, font_small = (
    pygame.font.Font(None, 72),
    pygame.font.Font(None, 36),
    pygame.font.Font(None, 24),
)


class ClientInterface:
    def __init__(self, player_id):
        self.player_id = player_id
        self.server_address = ("localhost", 44444)
        # self.server_address = ("localhost", 55556)

    def send_request(self, method, path, body_dict=None, max_retries=3, delay=2):
        for attempt in range(max_retries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(5)
                    sock.connect(self.server_address)

                    body_bytes = b""
                    headers = {
                        "Host": f"{self.server_address[0]}",
                        "Connection": "close",
                    }
                    if body_dict:
                        body_str = json.dumps(body_dict)
                        body_bytes = body_str.encode("utf-8")
                        headers["Content-Type"] = "application/json"
                        headers["Content-Length"] = len(body_bytes)

                    header_lines = "".join(
                        [f"{k}: {v}\r\n" for k, v in headers.items()]
                    )
                    request_str = (
                        f"{method.upper()} {path} HTTP/1.0\r\n{header_lines}\r\n"
                    )

                    sock.sendall(request_str.encode("utf-8") + body_bytes)

                    response_data = b""
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        response_data += chunk

                    if b"\r\n\r\n" in response_data:
                        _, body_part = response_data.split(b"\r\n\r\n", 1)
                        if body_part:
                            return json.loads(body_part.decode("utf-8"))

                    return {
                        "status": "ERROR",
                        "message": "Invalid response from server",
                    }
            except (
                ConnectionRefusedError,
                ConnectionResetError,
                socket.gaierror,
                socket.timeout,
            ) as e:
                logging.error(f"Request failed on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(delay)
                else:
                    return {"status": "ERROR", "message": "Connection to server lost."}
            except Exception as e:
                logging.error(f"An unexpected error occurred during request: {e}")
                return {"status": "ERROR", "message": str(e)}
        return {"status": "ERROR", "message": "Connection to server lost."}

    def register_player(self):
        return self.send_request("POST", f"/player/{self.player_id}")

    def create_game(self):
        return self.send_request("POST", f"/game/create/{self.player_id}")

    def join_game(self, game_id):
        return self.send_request(
            "POST", f"/game/join/{self.player_id}", {"game_id": game_id}
        )

    def spectate_game(self, game_id):
        return self.send_request(
            "POST", f"/game/spectate/{self.player_id}", {"game_id": game_id}
        )

    def make_move(self, row, col):
        return self.send_request(
            "POST", f"/move/{self.player_id}", {"row": row, "col": col}
        )

    def get_game_state(self):
        return self.send_request("GET", f"/game/state/{self.player_id}")

    def get_available_games(self):
        return self.send_request("GET", "/games")

    def get_history(self):
        return self.send_request("GET", f"/history/{self.player_id}")

    def leave_game(self):
        return self.send_request("POST", f"/game/leave/{self.player_id}")


class TicTacToeGame:
    def __init__(self, player_id):
        self.player_id = player_id
        self.client = ClientInterface(player_id)
        self.game_status = "menu"
        self.message = "Welcome to Tic Tac Toe!"
        self.board = [["." for _ in range(3)] for _ in range(3)]
        self.winner, self.current_turn, self.your_symbol, self.players, self.symbols = (
            None,
            None,
            None,
            [],
            {},
        )
        self.player_statuses = {}
        self.notification, self.notification_timer = None, 0
        self.available_games, self.lobby_buttons = [], []
        self.game_history = []
        self.is_disconnected = False
        self.reconnect_attempt_timer = 0
        
        self.resumable_game_status = None

        self.board_size = 450
        self.board_start_x = (WIDTH - self.board_size) // 2
        self.board_start_y = 150
        self.cell_size = self.board_size // 3

        self.attempt_initial_connection()

    def attempt_initial_connection(self):
        self.message = "Connecting to server..."
        result = self.client.register_player()
        if result.get("status") == "ERROR" and "Connection" in result.get("message", ""):
            self.is_disconnected = True
            self.message = result.get("message", "Could not connect.")
        else:
            self.is_disconnected = False
            self.message = result.get("message", "Registration failed.")
            self.update_game_state(check_for_resume=True)

    def handle_server_response(self, result):
        if result.get("status") == "ERROR" and "Connection" in result.get("message", ""):
            self.is_disconnected = True
            self.message = result.get("message", "Connection lost.")
            return False
        
        self.is_disconnected = False
        return True

    def draw_text(self, text, font, color, center_pos, background=None):
        text_render = font.render(text, True, color)
        rect = text_render.get_rect(center=center_pos)

        if background:
            bg_rect = rect.inflate(20, 10)
            pygame.draw.rect(screen, background, bg_rect)

        screen.blit(text_render, rect)
    
    def draw_connection_status(self):
        if self.is_disconnected:
            self.draw_text("Reconnecting...", font_medium, RED, (WIDTH // 2, HEIGHT - 30), YELLOW)
    
    def draw_menu(self):
        screen.fill(WHITE)
        self.draw_text("Tic Tac Toe", font_large, BLACK, (WIDTH // 2, 50))
        self.draw_text(f"Player: {self.player_id}", font_medium, BLUE, (WIDTH // 2, 120))
        
        y_pos = 180
        continue_button = None
        # Display Continue Game button if a game is resumable
        if self.resumable_game_status:
            continue_button = pygame.Rect(WIDTH // 2 - 125, y_pos, 250, 50)
            pygame.draw.rect(screen, YELLOW, continue_button)
            self.draw_text("Continue Game", font_medium, BLACK, continue_button.center)
            y_pos += 70

        create_button = pygame.Rect(WIDTH // 2 - 100, y_pos, 200, 50)
        y_pos += 70
        join_button = pygame.Rect(WIDTH // 2 - 100, y_pos, 200, 50)
        y_pos += 70
        history_btn = pygame.Rect(WIDTH // 2 - 125, y_pos, 250, 50)

        pygame.draw.rect(screen, GREEN, create_button)
        pygame.draw.rect(screen, BLUE, join_button)
        pygame.draw.rect(screen, LIGHT_GRAY, history_btn)
        
        self.draw_text("Create Game", font_medium, WHITE, create_button.center)
        self.draw_text("Game Lobby", font_medium, WHITE, join_button.center)
        self.draw_text("Game History", font_medium, WHITE, history_btn.center)

        if not self.is_disconnected:
            self.draw_text(self.message, font_small, BLACK, (WIDTH // 2, y_pos + 60))

        return continue_button, create_button, join_button, history_btn

    def draw_lobby_menu(self):
        screen.fill(WHITE)
        self.draw_text("Game Lobby", font_large, BLACK, (WIDTH // 2, 50))
        self.lobby_buttons.clear()
        y_offset = 120
        for game in self.available_games:
            game_text = f"Game {game['game_id']} (by {game['created_by']})"
            action_text, action_color, action_type = "", None, None
            if game["status"] == "waiting":
                action_text, action_color, action_type = "Join", GREEN, "join"
            elif game["status"] == "playing":
                action_text, action_color, action_type = "Spectate", ORANGE, "spectate"
            if action_type:
                game_rect = pygame.Rect(WIDTH // 2 - 250, y_offset, 350, 40)
                btn_rect = pygame.Rect(WIDTH // 2 + 110, y_offset, 140, 40)
                self.lobby_buttons.append((btn_rect, game["game_id"], action_type))
                pygame.draw.rect(screen, LIGHT_GRAY, game_rect)
                self.draw_text(game_text, font_small, BLACK, game_rect.center)
                pygame.draw.rect(screen, action_color, btn_rect)
                self.draw_text(action_text, font_small, WHITE, btn_rect.center)
                y_offset += 50
        if not self.available_games:
            self.draw_text("No games available.", font_medium, RED, (WIDTH // 2, 200))
        back_button = pygame.Rect(WIDTH // 2 - 75, HEIGHT - 80, 150, 40)
        pygame.draw.rect(screen, GRAY, back_button)
        self.draw_text("Back to Menu", font_small, WHITE, back_button.center)
        return back_button

    def draw_history_menu(self):
        screen.fill(WHITE)
        self.draw_text("Your Game History", font_large, BLACK, (WIDTH // 2, 50))
        y_offset = 120
        if not self.game_history:
            self.draw_text("No games played yet.", font_medium, RED, (WIDTH // 2, 200))
        else:
            for entry in self.game_history[-10:]:
                winner = entry.get("winner")
                outcome = "Victory" if winner == self.player_id else "Defeat" if winner not in ["draw", None] else "Draw"
                color = GREEN if outcome == "Victory" else RED if outcome == "Defeat" else BLACK
                try:
                    iso_date_str = entry["date"]
                    date_obj = datetime.datetime.fromisoformat(iso_date_str.split(".")[0])
                    date = date_obj.strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError, KeyError):
                    date = "Unknown Date"
                other_players = ", ".join(p for p in entry["players"] if p != self.player_id) or "Yourself"
                text = f"{date} - Vs {other_players} - {outcome}"
                self.draw_text(text, font_small, color, (WIDTH // 2, y_offset))
                y_offset += 40
        back_button = pygame.Rect(WIDTH // 2 - 75, HEIGHT - 80, 150, 40)
        pygame.draw.rect(screen, GRAY, back_button)
        self.draw_text("Back to Menu", font_small, WHITE, back_button.center)
        return back_button

    def draw_game(self):
        screen.fill(WHITE)
        title = "Spectator Mode" if self.game_status == "spectating" else "Tic Tac Toe"
        self.draw_text(title, font_medium, BLACK, (WIDTH // 2, 30))
        if self.your_symbol:
            self.draw_text(f"You are: {self.your_symbol}", font_small, BLUE, (80, 70))
        opponent_id = next((p for p in self.players if p != self.player_id), None)
        if opponent_id and self.player_statuses.get(opponent_id) == "offline":
            self.draw_text("Opponent disconnected...", font_medium, ORANGE, (WIDTH // 2, 100))
        elif self.game_status in ["playing", "spectating"] and self.current_turn:
            turn_msg = "YOUR TURN!" if self.current_turn == self.player_id else f"Turn: {self.current_turn}"
            color = GREEN if self.current_turn == self.player_id else BLACK
            self.draw_text(turn_msg, font_medium, color, (WIDTH // 2, 100))
        for i in range(4):
            pygame.draw.line(screen, BLACK, (self.board_start_x + i * self.cell_size, self.board_start_y), (self.board_start_x + i * self.cell_size, self.board_start_y + self.board_size), 3)
            pygame.draw.line(screen, BLACK, (self.board_start_x, self.board_start_y + i * self.cell_size), (self.board_start_x + self.board_size, self.board_start_y + i * self.cell_size), 3)
        for r, row_data in enumerate(self.board):
            for c, cell in enumerate(row_data):
                center = (self.board_start_x + c * self.cell_size + self.cell_size // 2, self.board_start_y + r * self.cell_size + self.cell_size // 2)
                if cell == "X":
                    pygame.draw.line(screen, RED, (center[0] - 40, center[1] - 40), (center[0] + 40, center[1] + 40), 8)
                    pygame.draw.line(screen, RED, (center[0] + 40, center[1] - 40), (center[0] - 40, center[1] + 40), 8)
                elif cell == "O":
                    pygame.draw.circle(screen, BLUE, center, 50, 8)
        status_y = self.board_start_y + self.board_size + 40
        status_msg = ""
        if self.game_status == "waiting": status_msg = "Waiting for another player..."
        elif self.game_status == "finished":
            if self.winner == "draw": status_msg = "Game ended in a draw!"
            elif self.winner == self.player_id: status_msg = "You won!"
            else: status_msg = f"Player '{self.winner}' won!"
        if not self.is_disconnected:
             self.draw_text(status_msg, font_medium, BLACK, (WIDTH // 2, status_y))
        if self.notification and self.notification_timer > 0:
            self.draw_text(self.notification, font_medium, WHITE, (WIDTH // 2, HEIGHT // 2), background=GREEN)
            self.notification_timer -= 1
        else: self.notification = None
        if self.game_status == "finished":
            menu_button = pygame.Rect(WIDTH // 2 - 75, status_y + 40, 150, 40)
            pygame.draw.rect(screen, GRAY, menu_button)
            self.draw_text("Back to Menu", font_small, WHITE, menu_button.center)
            return menu_button
        return None

    def handle_click(self, pos):
        if self.game_status == "playing" and self.current_turn == self.player_id:
            if self.board_start_x <= pos[0] <= self.board_start_x + self.board_size and self.board_start_y <= pos[1] <= self.board_start_y + self.board_size:
                col = (pos[0] - self.board_start_x) // self.cell_size
                row = (pos[1] - self.board_start_y) // self.cell_size
                if self.board[row][col] == ".":
                    result = self.client.make_move(row, col)
                    if self.handle_server_response(result):
                        if result.get("status") == "OK": self.update_from_state(result.get("game_state", {}))
                        else: self.message = result.get("message", "Failed to make move.")

    def update_from_state(self, state):
        if not state: return
        self.board = state.get("board", self.board)
        self.game_status = state.get("game_status", self.game_status)
        self.current_turn = state.get("current_turn", self.current_turn)
        self.winner = state.get("winner", self.winner)
        self.your_symbol = state.get("your_symbol", self.your_symbol)
        self.players = state.get("players", self.players)
        new_statuses = state.get("player_statuses", {})
        for p_id, status in new_statuses.items():
            if p_id != self.player_id and status == "online" and self.player_statuses.get(p_id) == "offline":
                self.notification, self.notification_timer = "Opponent has reconnected!", FPS * 3
        self.player_statuses = new_statuses

    def update_game_state(self, check_for_resume=False):
        """Checks for resumable games on startup, otherwise updates state normally."""
        result = self.client.get_game_state()
        if self.handle_server_response(result):
            if result.get("status") == "OK":
                game_state = result.get("game_state", {})
                if check_for_resume and game_state.get("game_status") in ["waiting", "playing", "spectating"]:
                    self.resumable_game_status = game_state.get("game_status")
                    self.message = "You have an ongoing game."
                else:
                    self.update_from_state(game_state)
            elif result.get("message") == "Player not in a game":
                self.resumable_game_status = None
                if self.game_status not in ["menu", "lobby", "history_menu"]:
                    self.back_to_menu(notify_server=False)

    def action_continue_game(self):
        """Action to jump back into a resumable game."""
        if self.resumable_game_status:
            self.game_status = self.resumable_game_status
            self.resumable_game_status = None
            self.update_game_state()

    def action_create_game(self):
        result = self.client.create_game()
        if self.handle_server_response(result) and result.get("status") == "OK":
            self.game_status = "waiting"
            self.update_game_state()
        else: self.message = result.get("message", "Failed to create game.")

    def action_join_game(self, game_id):
        result = self.client.join_game(game_id)
        if self.handle_server_response(result) and result.get("status") == "OK":
            self.game_status = "playing"
            self.update_from_state(result.get("game_state", {}))
        else: self.message = result.get("message", "Failed to join game.")

    def action_spectate_game(self, game_id):
        result = self.client.spectate_game(game_id)
        if self.handle_server_response(result) and result.get("status") == "OK":
            self.game_status = "spectating"
            self.update_from_state(result.get("game_state", {}))
        else: self.message = result.get("message", "Failed to spectate game.")

    def action_fetch_games(self):
        result = self.client.get_available_games()
        if self.handle_server_response(result) and result.get("status") == "OK":
            self.available_games = result.get("available_games", [])
            self.game_status = "lobby"
        else: self.message = result.get("message", "Can't fetch games.")

    def action_fetch_history(self):
        result = self.client.get_history()
        if self.handle_server_response(result) and result.get("status") == "OK":
            self.game_history = result.get("history", [])
            self.game_status = "history_menu"
        else: self.message = result.get("message", "Could not fetch game history.")

    def back_to_menu(self, notify_server=True):
        if notify_server and self.game_status in ["waiting", "playing", "spectating", "finished"]:
            result = self.client.leave_game()
            self.message = result.get("message", "Welcome back!")
        else:
            self.message = "Welcome back!"
        self.game_status = "menu"
        self.board = [["." for _ in range(3)] for _ in range(3)]
        self.winner, self.current_turn, self.your_symbol = None, None, None
        self.players, self.symbols = [], {}

    def run(self):
        running = True
        update_counter = 0
        buttons = {}

        while running:
            self.reconnect_attempt_timer += 1
            if self.is_disconnected and self.reconnect_attempt_timer > (FPS * 2):
                self.reconnect_attempt_timer = 0
                result = self.client.register_player()
                if self.handle_server_response(result):
                     self.message = "Reconnected! Resuming game..."
                     self.update_game_state(check_for_resume=True)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                if event.type == pygame.MOUSEBUTTONDOWN and not self.is_disconnected:
                    if self.game_status == "menu":
                        if buttons.get("continue") and buttons["continue"].collidepoint(event.pos): self.action_continue_game()
                        elif buttons.get("create") and buttons["create"].collidepoint(event.pos): self.action_create_game()
                        elif buttons.get("lobby") and buttons["lobby"].collidepoint(event.pos): self.action_fetch_games()
                        elif buttons.get("history") and buttons["history"].collidepoint(event.pos): self.action_fetch_history()
                    elif self.game_status == "lobby":
                        if buttons.get("back") and buttons["back"].collidepoint(event.pos): self.back_to_menu(notify_server=False)
                        for btn_rect, game_id, action in self.lobby_buttons:
                            if btn_rect.collidepoint(event.pos):
                                if action == "join": self.action_join_game(game_id)
                                elif action == "spectate": self.action_spectate_game(game_id)
                    elif self.game_status == "history_menu":
                        if buttons.get("back") and buttons["back"].collidepoint(event.pos): self.back_to_menu(notify_server=False)
                    elif self.game_status == "finished":
                        if buttons.get("back") and buttons["back"].collidepoint(event.pos): self.back_to_menu()
                    elif self.game_status == "playing":
                        self.handle_click(event.pos)

            update_counter += 1
            if update_counter > (FPS * 1.5) and not self.is_disconnected:
                if self.game_status in ["waiting", "playing", "spectating"]:
                    self.update_game_state()
                update_counter = 0

            screen.fill(WHITE)
            if self.game_status == "menu":
                cont_btn, create_btn, lobby_btn, hist_btn = self.draw_menu()
                buttons = {"continue": cont_btn, "create": create_btn, "lobby": lobby_btn, "history": hist_btn}
            elif self.game_status == "lobby":
                buttons["back"] = self.draw_lobby_menu()
            elif self.game_status == "history_menu":
                buttons["back"] = self.draw_history_menu()
            else:
                buttons["back"] = self.draw_game()

            self.draw_connection_status()
            pygame.display.flip()
            clock.tick(FPS)

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    player_id_input = input("Enter your player ID (or press Enter for a random one): ")
    if not player_id_input:
        player_id = f"player_{uuid.uuid4().hex[:6]}"
        print(f"No ID entered, using generated ID: {player_id}")
    else:
        player_id = player_id_input

    game = TicTacToeGame(player_id)
    game.run()