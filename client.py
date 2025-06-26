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
WHITE, BLACK, BLUE, RED, GREEN, GRAY, LIGHT_GRAY = (255, 255, 255), (0, 0, 0), (0, 100, 200), (200, 0, 0), (0, 200, 0), (128, 128, 128), (200, 200, 200)
font_large, font_medium, font_small = pygame.font.Font(None, 72), pygame.font.Font(None, 36), pygame.font.Font(None, 24)

class ClientInterface:
    def __init__(self, player_id):
        self.player_id = player_id
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
                
                # Handle cases where the response might not have a body
                if b'\r\n\r\n' in response_data:
                    header_part, body_part = response_data.split(b'\r\n\r\n', 1)
                    if body_part:
                        return json.loads(body_part.decode('utf-8'))
                
                return {"status": "ERROR", "message": "Invalid response from server"}
        except Exception as e:
            logging.error(f"Request failed: {e}")
            return {"status": "ERROR", "message": str(e)}

    def register_player(self):
        return self.send_request("POST", f"/player/{self.player_id}")

    def create_game(self):
        return self.send_request("POST", f"/game/create/{self.player_id}")

    def join_game(self, game_id):
        return self.send_request("POST", f"/game/join/{self.player_id}", {"game_id": game_id})

    def make_move(self, row, col):
        return self.send_request("POST", f"/move/{self.player_id}", {"row": row, "col": col})

    def get_game_state(self):
        return self.send_request("GET", f"/game/state/{self.player_id}")

    def get_available_games(self):
        return self.send_request("GET", "/games")

    def leave_game(self):
        """Notifies the server that the player is leaving the current game."""
        return self.send_request("POST", f"/game/leave/{self.player_id}")


class TicTacToeGame:
    def __init__(self, player_id):
        self.player_id = player_id
        self.client = ClientInterface(player_id)
        self.game_status = 'menu'  # menu, join_menu, waiting, playing, finished
        self.message = "Welcome to Tic Tac Toe!"
        self.board = [['.' for _ in range(3)] for _ in range(3)]
        self.winner, self.current_turn, self.your_symbol, self.players, self.symbols = None, None, None, [], {}
        self.available_games, self.join_buttons = [], []
        
        self.board_size = 450
        self.board_start_x = (WIDTH - self.board_size) // 2
        self.board_start_y = 150
        self.cell_size = self.board_size // 3
        
        # Register player
        result = self.client.register_player()
        self.message = result.get('message', 'Registration failed.')

    def draw_text(self, text, font, color, center_pos):
        render = font.render(text, True, color)
        rect = render.get_rect(center=center_pos)
        screen.blit(render, rect)

    def draw_menu(self):
        screen.fill(WHITE)
        self.draw_text("Tic Tac Toe", font_large, BLACK, (WIDTH//2, 50))
        self.draw_text(f"Player: {self.player_id}", font_medium, BLUE, (WIDTH//2, 120))
        
        create_button = pygame.Rect(WIDTH//2 - 100, 200, 200, 50)
        join_button = pygame.Rect(WIDTH//2 - 100, 270, 200, 50)
        
        pygame.draw.rect(screen, GREEN, create_button)
        pygame.draw.rect(screen, BLUE, join_button)
        
        self.draw_text("Create Game", font_medium, WHITE, create_button.center)
        self.draw_text("Join Game", font_medium, WHITE, join_button.center)
        self.draw_text(self.message, font_small, BLACK, (WIDTH//2, 350))
        
        return create_button, join_button

    def draw_join_menu(self):
        screen.fill(WHITE)
        self.draw_text("Available Games", font_large, BLACK, (WIDTH//2, 50))
        
        self.join_buttons.clear()
        y_offset = 120
        for game in self.available_games:
            game_text = f"Game {game['game_id']} (created by {game['created_by']})"
            btn_rect = pygame.Rect(WIDTH//2 - 200, y_offset, 400, 40)
            self.join_buttons.append((btn_rect, game['game_id']))
            pygame.draw.rect(screen, LIGHT_GRAY, btn_rect)
            self.draw_text(game_text, font_small, BLACK, btn_rect.center)
            y_offset += 50
        
        if not self.available_games:
            self.draw_text("No games available. Create one!", font_medium, RED, (WIDTH//2, 200))

        back_button = pygame.Rect(WIDTH//2 - 75, HEIGHT - 80, 150, 40)
        pygame.draw.rect(screen, GRAY, back_button)
        self.draw_text("Back to Menu", font_small, WHITE, back_button.center)
        return back_button

    def draw_game(self):
        screen.fill(WHITE)
        self.draw_text("Tic Tac Toe", font_medium, BLACK, (WIDTH//2, 30))
        
        if self.your_symbol:
            self.draw_text(f"You are: {self.your_symbol}", font_small, BLUE, (80, 70))

        if self.game_status == 'playing' and self.current_turn:
            turn_msg = "YOUR TURN!" if self.current_turn == self.player_id else f"Turn: {self.current_turn}"
            color = GREEN if self.current_turn == self.player_id else BLACK
            self.draw_text(turn_msg, font_medium, color, (WIDTH//2, 100))

        # Draw board and pieces
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
        if self.game_status == 'waiting': status_msg = "Waiting for another player..."
        elif self.game_status == 'finished':
            if self.winner == 'draw': status_msg = "Game ended in a draw!"
            elif self.winner == self.your_symbol: status_msg = "You won!"
            else: status_msg = f"Player with '{self.winner}' won!"
        self.draw_text(status_msg, font_medium, BLACK, (WIDTH//2, status_y))

        if self.game_status == 'finished':
            menu_button = pygame.Rect(WIDTH//2 - 75, status_y + 40, 150, 40)
            pygame.draw.rect(screen, GRAY, menu_button)
            self.draw_text("Back to Menu", font_small, WHITE, menu_button.center)
            return menu_button
        return None

    def handle_click(self, pos):
        if self.game_status == 'playing' and self.current_turn == self.player_id:
            if self.board_start_x <= pos[0] <= self.board_start_x + self.board_size and \
               self.board_start_y <= pos[1] <= self.board_start_y + self.board_size:
                col = (pos[0] - self.board_start_x) // self.cell_size
                row = (pos[1] - self.board_start_y) // self.cell_size
                if self.board[row][col] == '.':
                    result = self.client.make_move(row, col)
                    if result.get('status') == 'OK':
                        # The server now returns the game state on a successful move
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
            self.update_game_state()
        else:
            self.message = result.get('message', 'Failed to join game.')

    def action_fetch_games(self):
        result = self.client.get_available_games()
        if result.get('status') == 'OK':
            self.available_games = result.get('available_games', [])
            self.game_status = 'join_menu'
        else:
            self.message = result.get('message', "Can't fetch games.")

    def update_game_state(self):
        # Only poll if we are in an active game
        if self.game_status not in ['waiting', 'playing']:
            return
        result = self.client.get_game_state()
        if result.get('status') == 'OK':
            self.update_from_state(result.get('game_state', {}))
        elif result.get("message") == "Player not in a game":
            # This can happen if the server removed the game, move back to menu
            self.back_to_menu(notify_server=False)


    def back_to_menu(self, notify_server=True):
        """Notifies server (optional) and resets local state."""
        if notify_server:
            result = self.client.leave_game()
            self.message = result.get('message', "Welcome back!")
        else:
            self.message = "Welcome back!"

        self.game_status = 'menu'
        self.board = [['.' for _ in range(3)] for _ in range(3)]
        self.winner, self.current_turn, self.your_symbol = None, None, None
        self.players, self.symbols = [], {}


    def run(self):
        running = True
        update_counter = 0

        # Button rects to be checked against mouse clicks in the event loop
        create_btn_rect, join_btn_rect = None, None
        back_from_join_rect = None
        back_from_game_rect = None

        while running:
            # --- 1. Event Handling ---
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if self.game_status == 'menu':
                        if create_btn_rect and create_btn_rect.collidepoint(event.pos):
                            self.action_create_game()
                        elif join_btn_rect and join_btn_rect.collidepoint(event.pos):
                            self.action_fetch_games()
                    
                    elif self.game_status == 'join_menu':
                        if back_from_join_rect and back_from_join_rect.collidepoint(event.pos):
                            self.back_to_menu()
                        for btn_rect, game_id in self.join_buttons:
                            if btn_rect.collidepoint(event.pos):
                                self.action_join_game(game_id)
                    
                    elif self.game_status == 'finished':
                        if back_from_game_rect and back_from_game_rect.collidepoint(event.pos):
                            self.back_to_menu()
                    
                    elif self.game_status == 'playing':
                        self.handle_click(event.pos)

            # --- 2. Game Logic/State Updates (Polling) ---
            update_counter += 1
            if update_counter > (FPS * 1.5): # Poll every ~1.5 seconds
                self.update_game_state()
                update_counter = 0

            # --- 3. Drawing ---
            if self.game_status == 'menu':
                create_btn_rect, join_btn_rect = self.draw_menu()
            elif self.game_status == 'join_menu':
                back_from_join_rect = self.draw_join_menu() # This also populates self.join_buttons
            else: # Covers 'waiting', 'playing', 'finished'
                back_from_game_rect = self.draw_game()
            
            # --- 4. Update Display ---
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

