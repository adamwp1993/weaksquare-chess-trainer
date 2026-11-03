// Name the idea first (FR-4.3): the two pickers. They mirror IDEA_SETUP / IDEA_PAYOFF in
// src/weaksquare/core/themes.py (tests/contract/test_idea_lists.py keeps them equal). The split only
// helps you think: a tag counts wherever you put it, because Lichess doesn't record which role a theme plays.

export const IDEA_SETUP: [string, string][] = [
  ["attraction", "Attraction"],
  ["clearance", "Clearance"],
  ["defensiveMove", "Defensive move"],
  ["deflection", "Deflection"],
  ["interference", "Interference"],
  ["intermezzo", "Intermezzo"],
  ["quietMove", "Quiet move"],
  ["xRayAttack", "X-Ray attack"],
  ["zugzwang", "Zugzwang"],
  ["sacrifice", "Sacrifice"],
  ["capturingDefender", "Capture the defender"],
  ["discoveredAttack", "Discovered attack"],
];

export const IDEA_PAYOFF: [string, string][] = [
  ["advancedPawn", "Advanced pawn"],
  ["attackingF2F7", "Attacking f2 or f7"],
  ["discoveredCheck", "Discovered check"],
  ["doubleCheck", "Double check"],
  ["exposedKing", "Exposed king"],
  ["fork", "Fork"],
  ["hangingPiece", "Hanging piece"],
  ["kingsideAttack", "Kingside attack"],
  ["pin", "Pin"],
  ["queensideAttack", "Queenside attack"],
  ["skewer", "Skewer"],
  ["trappedPiece", "Trapped piece"],
  ["anastasiaMate", "Anastasia's mate"],
  ["arabianMate", "Arabian mate"],
  ["backRankMate", "Back rank mate"],
  ["balestraMate", "Balestra mate"],
  ["blindSwineMate", "Blind swine mate"],
  ["bodenMate", "Boden's mate"],
  ["cornerMate", "Corner mate"],
  ["doubleBishopMate", "Double bishop mate"],
  ["dovetailMate", "Dovetail mate"],
  ["epauletteMate", "Epaulette mate"],
  ["hookMate", "Hook mate"],
  ["killBoxMate", "Kill box mate"],
  ["morphysMate", "Morphy's mate"],
  ["operaMate", "Opera mate"],
  ["pillsburysMate", "Pillsbury's mate"],
  ["smotheredMate", "Smothered mate"],
  ["swallowstailMate", "Swallow's tail mate"],
  ["triangleMate", "Triangle mate"],
  ["vukovicMate", "Vukovič mate"],
  ["castling", "Castling"],
  ["enPassant", "En passant"],
  ["promotion", "Promotion"],
  ["underPromotion", "Underpromotion"],
];

export const MAX_TAGS_PER_SLOT = 3;
