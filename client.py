import datetime
import pygame
import sys
import socket
import json
import logging
import uuid

logging.basicConfig(level=logging.INFO)

# Initialize Pygame
pygame.init()

WIDTH, HEIGHT = 600, 700
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Multiplayer Tic Tac Toe (HTTP)")

clock = pygame.time.Clock()
FPS = 30 # Polling can be slower

# Colors & Fonts
WHITE, BLACK, BLUE, RED, GREEN, GRAY, LIGHT_GRAY, ORANGE = (255, 255, 255), (0, 0, 0), (0, 100, 200), (200, 0, 0), (0, 200, 0), (128, 128, 128), (200, 200, 200), (255, 165, 0)
font_large, font_medium, font_small = pygame.font.Font(None, 72), pygame.font.Font(None, 36), pygame.font.Font(None, 24)

class ClientInterface:
    def __init__(self, username):
        self.username = username
        self.server_address = ('localhost', 55556)

    def send_request(self, method, path, body_dict=None):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(self.server_address)

                body_bytes = b''
                headers = {"Host": f"{self.server_address[0]}", "Connection": "close"}
                if body_dict:
                    body_str = json.dumps(body_dict)
                    body_bytes = body_str.encode('utf-8')
                    headers["Content-Type"] = "application/json"
                    headers["Content-Length"] = len(body_bytes)

                header_lines = "".join([f"{k}: {v}\r\n" for k, v in headers.items()])
                request_str = f"{method.upper()} {path} HTTP/1.0\r\n{header_lines}\r\n"

                sock.sendall(request_str.encode('utf-8') + body_bytes)

                response_data = b''
                while True:
                    chunk = sock.recv(4096)
                    if not chunk: break
                    response_data += chunk

                if b'\r\n\r\n' in response_data:
                    header_part, body_part = response_data.split(b'\r\n\r\n', 1)
                    if body_part:
                        return json.loads(body_part.decode('utf-8'))

                return {"status": "ERROR", "message": "Invalid response from server"}
        except Exception as e:
            logging.error(f"Request failed: {e}")
            return {"status": "ERROR", "message": str(e)}

    def register(self, username, password):
        return self.send_request("POST", "/register", {"username": username, "password": password})

    def login(self, username, password):
        return self.send_request("POST", "/login", {"username": username, "password": password})

    def create_game(self):
        return self.send_request("POST", f"/game/create/{self.username}")

    def join_game(self, game_id):
        return self.send_request("POST", f"/game/join/{self.username}", {"game_id": game_id})
    
    def spectate_game(self, game_id):
        return self.send_request("POST", f"/game/spectate/{self.username}", {"game_id": game_id})

    def make_move(self, row, col):
        return self.send_request("POST", f"/move/{self.username}", {"row": row, "col": col})

    def get_game_state(self):
        return self.send_request("GET", f"/game/state/{self.username}")

    def get_available_games(self):
        return self.send_request("GET", "/games")

    def get_history(self):
        return self.send_request("GET", f"/history/{self.username}")

    def leave_game(self):
        return self.send_request("POST", f"/game/leave/{self.username}")

    def disconnect(self):
        return self.send_request("POST", f"/disconnect/{self.username}")


class TicTacToeGame:
    def __init__(self):
        self.username = None
        self.client = ClientInterface(None) # Temporary client for login/register
        self.game_status = 'login' # Always start at login
        self.login_mode = 'login' # or 'register'
        self.message = "Enter your credentials"
        
        self.board = [['.' for _ in range(3)] for _ in range(3)]
        self.winner, self.current_turn, self.your_symbol, self.players, self.symbols = None, None, None, [], {}
        self.disconnected_players = []
        self.available_games, self.lobby_buttons = [], []
        self.game_history = []

        # Input fields
        self.username_text = ''
        self.password_text = ''
        self.active_input = 'username' # 'username' or 'password'
        
        self.board_size = 450
        self.board_start_x = (WIDTH - self.board_size) // 2
        self.board_start_y = 150
        self.cell_size = self.board_size // 3

    def draw_text(self, text, font, color, center_pos):
        render = font.render(text, True, color)
        rect = render.get_rect(center=center_pos)
        screen.blit(render, rect)

    def draw_login_screen(self):
        screen.fill(WHITE)
        title = "Login" if self.login_mode == 'login' else "Register"
        self.draw_text(title, font_large, BLACK, (WIDTH//2, 80))

        # Username field
        self.draw_text("Username", font_small, BLACK, (WIDTH//2, 150))
        username_rect = pygame.Rect(WIDTH//2 - 150, 170, 300, 40)
        pygame.draw.rect(screen, LIGHT_GRAY, username_rect)
        pygame.draw.rect(screen, BLACK if self.active_input == 'username' else GRAY, username_rect, 2)
        self.draw_text(self.username_text, font_medium, BLACK, username_rect.center)

        # Password field
        self.draw_text("Password", font_small, BLACK, (WIDTH//2, 230))
        password_rect = pygame.Rect(WIDTH//2 - 150, 250, 300, 40)
        pygame.draw.rect(screen, LIGHT_GRAY, password_rect)
        pygame.draw.rect(screen, BLACK if self.active_input == 'password' else GRAY, password_rect, 2)
        self.draw_text('*' * len(self.password_text), font_medium, BLACK, password_rect.center)

        # Buttons
        action_button = pygame.Rect(WIDTH//2 - 100, 320, 200, 50)
        pygame.draw.rect(screen, GREEN, action_button)
        self.draw_text(title, font_medium, WHITE, action_button.center)

        switch_mode_button = pygame.Rect(WIDTH//2 - 150, 390, 300, 40)
        switch_text = "Don't have an account? Register" if self.login_mode == 'login' else "Already have an account? Login"
        self.draw_text(switch_text, font_small, BLUE, switch_mode_button.center)
        
        self.draw_text(self.message, font_small, RED, (WIDTH//2, 450))

        return username_rect, password_rect, action_button, switch_mode_button

    def draw_menu(self):
        screen.fill(WHITE)
        self.draw_text("Tic Tac Toe", font_large, BLACK, (WIDTH//2, 50))
        self.draw_text(f"Player: {self.username}", font_medium, BLUE, (WIDTH//2, 120))
        
        y_start = 200
        create_button = pygame.Rect(WIDTH//2 - 100, y_start, 200, 50)
        join_button = pygame.Rect(WIDTH//2 - 100, y_start + 70, 200, 50)
        history_btn = pygame.Rect(WIDTH//2 - 125, y_start + 140, 250, 50)
        
        pygame.draw.rect(screen, GREEN, create_button)
        pygame.draw.rect(screen, BLUE, join_button)
        pygame.draw.rect(screen, LIGHT_GRAY, history_btn)
        
        self.draw_text("Create Game", font_medium, WHITE, create_button.center)
        self.draw_text("Game Lobby", font_medium, WHITE, join_button.center)
        self.draw_text("Game History", font_medium, WHITE, history_btn.center)
        self.draw_text(self.message, font_small, BLACK, (WIDTH//2, y_start + 210))
        
        return create_button, join_button, history_btn

    def draw_lobby_menu(self):
        screen.fill(WHITE)
        self.draw_text("Game Lobby", font_large, BLACK, (WIDTH//2, 50))
        
        self.lobby_buttons.clear()
        y_offset = 120
        for game in self.available_games:
            game_text = f"Game {game['game_id']} (by {game['created_by']})"
            
            # Action button (Join or Spectate)
            action_text = ""
            action_color = None
            action_type = None

            if game['status'] == 'waiting':
                action_text = "Join"
                action_color = GREEN
                action_type = 'join'
            elif game['status'] == 'playing':
                action_text = "Spectate"
                action_color = ORANGE
                action_type = 'spectate'

            if action_type:
                game_rect = pygame.Rect(WIDTH//2 - 250, y_offset, 350, 40)
                btn_rect = pygame.Rect(WIDTH//2 + 110, y_offset, 140, 40)
                self.lobby_buttons.append((btn_rect, game['game_id'], action_type))

                pygame.draw.rect(screen, LIGHT_GRAY, game_rect)
                self.draw_text(game_text, font_small, BLACK, game_rect.center)
                pygame.draw.rect(screen, action_color, btn_rect)
                self.draw_text(action_text, font_small, WHITE, btn_rect.center)
                y_offset += 50
        
        if not self.available_games:
            self.draw_text("No games available. Create one!", font_medium, RED, (WIDTH//2, 200))

        back_button = pygame.Rect(WIDTH//2 - 75, HEIGHT - 80, 150, 40)
        pygame.draw.rect(screen, GRAY, back_button)
        self.draw_text("Back to Menu", font_small, WHITE, back_button.center)
        return back_button

    def draw_history_menu(self):
        screen.fill(WHITE)
        self.draw_text("Your Game History", font_large, BLACK, (WIDTH//2, 50))
        y_offset = 120
        if not self.game_history:
             self.draw_text("No games played yet.", font_medium, RED, (WIDTH//2, 200))
        else:
            for entry in self.game_history[-10:]: # Show last 10 games
                winner = entry.get('winner')
                
                outcome = "Victory" if winner == self.username else "Defeat" if winner not in ['draw', None] else "Draw"
                color = GREEN if outcome == "Victory" else RED if outcome == "Defeat" else BLACK
                
                try: date = datetime.datetime.fromisoformat(entry['date']).strftime('%Y-%m-%d %H:%M')
                except (ValueError, TypeError): date = "Unknown Date"
                    
                other_players = ', '.join(p for p in entry['players'] if p != self.username)
                if not other_players: other_players = "Yourself" 
                text = f"{date} - Vs {other_players} - {outcome}"
                
                self.draw_text(text, font_small, color, (WIDTH//2, y_offset))
                y_offset += 40
        
        back_button = pygame.Rect(WIDTH//2 - 75, HEIGHT - 80, 150, 40)
        pygame.draw.rect(screen, GRAY, back_button)
        self.draw_text("Back to Menu", font_small, WHITE, back_button.center)
        return back_button


    def draw_game(self):
        screen.fill(WHITE)
        title = "Tic Tac Toe"
        if self.game_status == 'spectating':
            title = "Spectator Mode"
        self.draw_text(title, font_medium, BLACK, (WIDTH//2, 30))
        
        if self.your_symbol:
            self.draw_text(f"You are: {self.your_symbol}", font_small, BLUE, (80, 70))

        if self.game_status == 'playing' and self.current_turn:
            turn_msg = "YOUR TURN!" if self.current_turn == self.username else f"Turn: {self.current_turn}"
            color = GREEN if self.current_turn == self.username else BLACK
            self.draw_text(turn_msg, font_medium, color, (WIDTH//2, 100))
        elif self.game_status == 'spectating' and self.current_turn:
             self.draw_text(f"Turn: {self.current_turn}", font_medium, BLACK, (WIDTH//2, 100))
        elif self.game_status == 'disconnected':
            self.draw_text("A player has disconnected.", font_medium, RED, (WIDTH//2, 100))

        for i in range(4):
            pygame.draw.line(screen, BLACK, (self.board_start_x + i * self.cell_size, self.board_start_y), (self.board_start_x + i * self.cell_size, self.board_start_y + self.board_size), 3)
            pygame.draw.line(screen, BLACK, (self.board_start_x, self.board_start_y + i * self.cell_size), (self.board_start_x + self.board_size, self.board_start_y + i * self.cell_size), 3)

        for r, row_data in enumerate(self.board):
            for c, cell in enumerate(row_data):
                center = (self.board_start_x + c * self.cell_size + self.cell_size//2, self.board_start_y + r * self.cell_size + self.cell_size//2)
                if cell == 'X':
                    pygame.draw.line(screen, RED, (center[0]-40, center[1]-40), (center[0]+40, center[1]+40), 8)
                    pygame.draw.line(screen, RED, (center[0]+40, center[1]-40), (center[0]-40, center[1]+40), 8)
                elif cell == 'O':
                    pygame.draw.circle(screen, BLUE, center, 50, 8)
        
        status_y = self.board_start_y + self.board_size + 40
        status_msg = ""
        if self.game_status == 'waiting':
            status_msg = "Waiting for another player..."
        elif self.game_status == 'disconnected':
            disconnected_list = ", ".join(self.disconnected_players)
            status_msg = f"Waiting for {disconnected_list} to reconnect..."
        elif self.game_status == 'finished':
            winner_id = self.winner
            if winner_id == 'draw':
                status_msg = "Game ended in a draw!"
            elif winner_id == self.username:
                status_msg = "You won! :)"
            elif winner_id:
                status_msg = "You lose! :("
            else: # Should not happen, but as a fallback
                status_msg = "Game Over"
        
        # Default message if status is 'playing' or something else
        if not status_msg and self.game_status == 'playing':
            # This space is intentionally left blank as the turn indicator is shown above the board
            pass
        
        self.draw_text(status_msg, font_medium, BLACK, (WIDTH//2, status_y))

        if self.game_status == 'finished':
            menu_button = pygame.Rect(WIDTH//2 - 75, status_y + 40, 150, 40)
            pygame.draw.rect(screen, GRAY, menu_button)
            self.draw_text("Back to Menu", font_small, WHITE, menu_button.center)
            return menu_button
        return None

    def handle_click(self, pos):
        if self.game_status == 'playing' and self.current_turn == self.username:
            if self.board_start_x <= pos[0] <= self.board_start_x + self.board_size and \
               self.board_start_y <= pos[1] <= self.board_start_y + self.board_size:
                col = (pos[0] - self.board_start_x) // self.cell_size
                row = (pos[1] - self.board_start_y) // self.cell_size
                if self.board[row][col] == '.':
                    result = self.client.make_move(row, col)
                    if result.get('status') == 'OK':
                        self.update_from_state(result.get('game_state', {}))
                    else:
                        self.message = result.get('message', 'Failed to make move.')

    def update_from_state(self, state):
        if not state: return
        self.board = state.get('board', self.board)
        self.game_status = state.get('game_status', self.game_status)
        self.current_turn = state.get('current_turn', self.current_turn)
        self.winner = state.get('winner', self.winner)
        self.your_symbol = state.get('your_symbol', self.your_symbol)
        self.disconnected_players = state.get('disconnected_players', [])

    def action_create_game(self):
        result = self.client.create_game()
        if result.get('status') == 'OK':
            self.game_status = 'waiting'
            self.update_game_state()
        else:
            self.message = result.get('message', 'Failed to create game.')

    def action_join_game(self, game_id):
        result = self.client.join_game(game_id)
        if result.get('status') == 'OK':
            self.game_status = 'playing'
            self.update_from_state(result.get('game_state', {}))
        else:
            self.message = result.get('message', 'Failed to join game.')
            
    def action_spectate_game(self, game_id):
        result = self.client.spectate_game(game_id)
        if result.get('status') == 'OK':
            self.game_status = 'spectating'
            self.update_from_state(result.get('game_state', {}))
        else:
            self.message = result.get('message', 'Failed to spectate game.')

    def action_fetch_games(self):
        result = self.client.get_available_games()
        if result.get('status') == 'OK':
            self.available_games = result.get('available_games', [])
            self.game_status = 'lobby'
        else:
            self.message = result.get('message', "Can't fetch games.")

    def action_fetch_history(self):
        result = self.client.get_history()
        if result.get('status') == 'OK':
            self.game_history = result.get('history', []) 
            self.game_status = 'history_menu'
        else:
            self.message = result.get('message', "Could not fetch game history.")

    def update_game_state(self):
        if self.game_status not in ['waiting', 'playing', 'spectating', 'disconnected']:
            return
        result = self.client.get_game_state()
        if result.get('status') == 'OK':
            self.update_from_state(result.get('game_state', {}))
        elif "not in a game" in result.get("message", ""):
            self.message = "The game has ended."
            self.back_to_menu(notify_server=False)
        elif result.get('status') == 'ERROR':
            # Handle server connection loss
            self.game_status = 'disconnected'
            self.message = "Connection lost. Attempting to reconnect..."
            # In a real app, you might have a more robust reconnection loop here
            # For now, we just show a message and the user can use the "Continue" button
            self.back_to_menu(notify_server=False)


    def back_to_menu(self, notify_server=True):
        if notify_server and self.game_status in ['waiting', 'playing', 'spectating', 'finished', 'disconnected']:
            result = self.client.leave_game()
            self.message = result.get('message', "Welcome back!")
        else:
            self.message = "Welcome back!"

        self.game_status = 'menu'
        self.board = [['.' for _ in range(3)] for _ in range(3)]
        self.winner, self.current_turn, self.your_symbol = None, None, None
        self.players, self.symbols, self.disconnected_players = [], {}, []


    def run(self):
        running = True
        update_counter = 0

        # Button rects
        create_btn, lobby_btn, history_btn = None, None, None
        back_from_lobby_btn, back_from_game_btn, back_from_history_btn = None, None, None
        username_rect, password_rect, action_btn, switch_mode_btn = None, None, None, None

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                
                if self.game_status == 'login':
                    if event.type == pygame.MOUSEBUTTONDOWN:
                        if username_rect and username_rect.collidepoint(event.pos):
                            self.active_input = 'username'
                        elif password_rect and password_rect.collidepoint(event.pos):
                            self.active_input = 'password'
                        elif action_btn and action_btn.collidepoint(event.pos):
                            self.handle_login_register()
                        elif switch_mode_btn and switch_mode_btn.collidepoint(event.pos):
                            self.login_mode = 'register' if self.login_mode == 'login' else 'login'
                            self.message = "Enter your credentials"
                    
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_RETURN:
                            self.handle_login_register()
                        elif event.key == pygame.K_BACKSPACE:
                            if self.active_input == 'username':
                                self.username_text = self.username_text[:-1]
                            else:
                                self.password_text = self.password_text[:-1]
                        else:
                            if self.active_input == 'username':
                                self.username_text += event.unicode
                            else:
                                self.password_text += event.unicode

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if self.game_status == 'menu':
                        if create_btn and create_btn.collidepoint(event.pos): self.action_create_game()
                        elif lobby_btn and lobby_btn.collidepoint(event.pos): self.action_fetch_games()
                        elif history_btn and history_btn.collidepoint(event.pos): self.action_fetch_history()
                    
                    elif self.game_status == 'lobby':
                        if back_from_lobby_btn and back_from_lobby_btn.collidepoint(event.pos): self.back_to_menu(notify_server=False)
                        for btn_rect, game_id, action in self.lobby_buttons:
                            if btn_rect.collidepoint(event.pos):
                                if action == 'join': self.action_join_game(game_id)
                                elif action == 'spectate': self.action_spectate_game(game_id)

                    elif self.game_status == 'history_menu':
                        if back_from_history_btn and back_from_history_btn.collidepoint(event.pos): self.back_to_menu(notify_server=False)
                    
                    elif self.game_status == 'finished':
                        if back_from_game_btn and back_from_game_btn.collidepoint(event.pos): self.back_to_menu(notify_server=False)
                    
                    elif self.game_status == 'playing':
                        self.handle_click(event.pos)

            update_counter += 1
            if update_counter > (FPS * 1.5) and self.client and self.username:
                self.update_game_state()
                update_counter = 0

            if self.game_status == 'login':
                username_rect, password_rect, action_btn, switch_mode_btn = self.draw_login_screen()
            elif self.game_status == 'menu':
                create_btn, lobby_btn, history_btn = self.draw_menu()
            elif self.game_status == 'lobby':
                back_from_lobby_btn = self.draw_lobby_menu()
            elif self.game_status == 'history_menu':
                back_from_history_btn = self.draw_history_menu()
            else: # Covers 'waiting', 'playing', 'spectating', 'finished'
                back_from_game_btn = self.draw_game()
            
            pygame.display.flip()
            clock.tick(FPS)
            
        # Notify server on window close if in an active game/session
        if self.client and self.game_status != 'menu':
            self.client.disconnect()
            
        pygame.quit()
        sys.exit()

    def handle_login_register(self):
        if not self.username_text or not self.password_text:
            self.message = "Username and password cannot be empty."
            return

        if self.login_mode == 'login':
            result = self.client.login(self.username_text, self.password_text)
            if result.get('status') == 'OK':
                self.username = self.username_text
                self.client.username = self.username # Update client's username
                self.message = result.get('message')
                if result.get('game_state'):
                    self.update_from_state(result['game_state'])
                else:
                    self.game_status = 'menu'
            else:
                self.message = result.get('message', 'Login failed.')
        
        else: # register
            result = self.client.register(self.username_text, self.password_text)
            self.message = result.get('message', 'Registration failed.')
            if result.get('status') == 'OK':
                self.login_mode = 'login' # Switch to login after successful registration

if __name__ == "__main__":
    game = TicTacToeGame()
    game.run()
