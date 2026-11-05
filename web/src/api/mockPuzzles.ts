// Fixed puzzles for the mock client, taken from tests/fixtures/puzzles_sample.csv (Lichess puzzle DB, CC0).
// Generated once; edit freely. Order is the order the mock serves them in.
export interface MockPuzzle {
  id: string;
  fen: string;
  moves: string[];
  rating: number;
  themes: string[];
  popularity?: number; // default 90
  plays?: number; // default 1,000
  openings?: string[]; // OpeningTags (family, then variation)
  source?: "my"; // v0.8: one of your own puzzles: moves[0] is "" (no opponent move first)
  origin?: string;
  set_label?: string | null;
  solve_as?: "you" | "opponent"; // v0.10: an Allowed puzzle from your games (FR-10.42)
  game_id?: number; // v0.10: the game it came from (FR-10.44)
  ply?: number;
  severity?: string; // v0.10: blunder / mistake / inaccuracy (FR-10.40)
}

export const MOCK_PUZZLES: MockPuzzle[] = [
  {"id": "DtKOy", "fen": "5rk1/5ppp/4p3/1qPnpP2/r2n4/P1BP2N1/6PP/R2Q1R1K w - - 1 26", "moves": ["a1b1", "d5c3", "b1b5", "c3d1"], "rating": 1403, "themes": ["advantage", "fork", "hangingPiece", "middlegame", "short"]},
  {"id": "IRypK", "fen": "8/5k2/7p/pK5P/P2N2R1/1P3Pp1/6r1/2r5 b - - 7 49", "moves": ["g2g1", "d4e2", "g1f1", "e2c1"], "rating": 1594, "themes": ["crushing", "endgame", "fork", "master", "short"]},
  {"id": "UjLNn", "fen": "1r3rk1/p4pp1/2p1pb1p/q1Pp4/P2N4/4P2P/2Q2PP1/2R2RK1 b - - 2 19", "moves": ["b8b4", "d4c6", "a5a4", "c6b4"], "rating": 1137, "themes": ["advantage", "fork", "middlegame", "short"]},
  {"id": "VCS0Z", "fen": "5r2/p1p2p2/4nPkp/2N1R1p1/5p2/1PP2K2/P5PP/8 b - - 0 36", "moves": ["g6f6", "c5d7", "f6g7", "d7f8"], "rating": 1128, "themes": ["advantage", "endgame", "fork", "short"]},
  {"id": "f0LoG", "fen": "8/5q2/3k4/7K/P3R1B1/7N/8/8 w - - 3 57", "moves": ["h5h4", "f7h7", "h4g3", "h7e4"], "rating": 1190, "themes": ["crushing", "endgame", "fork", "short"]},
  {"id": "001KR", "fen": "6Qk/p1p3pp/4N3/1p6/2q1r1n1/2B5/PP4PP/3R1R1K b - - 0 28", "moves": ["h8g8", "f1f8"], "rating": 563, "themes": ["mate", "mateIn1", "middlegame", "oneMove"]},
  {"id": "01RLM", "fen": "3rk2r/ppp2ppp/5n2/4p3/4P1b1/2P2N2/PPP2PPP/R1B1K2R w KQk - 0 9", "moves": ["f3e5", "d8d1"], "rating": 883, "themes": ["mate", "mateIn1", "middlegame", "oneMove"], "openings": ["Russian_Game", "Russian_Game_Damiano_Variation"]},
  {"id": "03cYQ", "fen": "6rk/2p2q2/1p4rp/2PR1b1p/P6Q/1P2p1PP/5P1N/3R2K1 w - - 0 36", "moves": ["h2f3", "f5g4", "h3g4", "f7f3", "d5h5", "f3d1"], "rating": 2818, "themes": ["advantage", "discoveredAttack", "kingsideAttack", "long", "middlegame"]},
  {"id": "04TL9", "fen": "8/8/4K1p1/p5P1/4P3/8/4k3/8 w - - 0 57", "moves": ["e6f6", "a5a4", "e4e5", "a4a3", "f6f7", "a3a2", "e5e6", "a2a1q"], "rating": 485, "themes": ["advancedPawn", "crushing", "endgame", "pawnEndgame", "promotion", "quietMove", "veryLong"]},
  {"id": "0OT49", "fen": "2r2rk1/5pbp/1q2p1p1/4P3/pB1pQP2/Pp1P4/1P4PP/2R2R1K b - - 1 25", "moves": ["f7f5", "e5f6", "g7f6", "b4f8"], "rating": 1898, "themes": ["crushing", "enPassant", "middlegame", "short"], "popularity": 60, "plays": 150},
];
