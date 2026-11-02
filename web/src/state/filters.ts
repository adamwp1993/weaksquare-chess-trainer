import type { FilterSpec } from "../api/types";

// The defaults match core/filters.py FilterSpec(): every theme, the light quality filter
// (popularity >= 50, >= 100 plays), puzzles you've solved here or played on Lichess left out,
// a queue of 20.
export const DEFAULT_MIN_POPULARITY = 50;
export const DEFAULT_MIN_PLAYS = 100;

export function defaultFilters(): FilterSpec {
  return {
    themes: [],
    match: "any",
    exclude_themes: [],
    rating_min: null,
    rating_max: null,
    lengths: [],
    side: "either",
    order: "random",
    queue_size: 20,
    openings: [],
    min_popularity: DEFAULT_MIN_POPULARITY,
    min_plays: DEFAULT_MIN_PLAYS,
    exclude_solved_here: true,
    exclude_played_on_lichess: true,
    only_my_misses: false,
    ratios: [],
    source: "lichess",
  };
}

export const LENGTH_OPTIONS: { value: number; label: string }[] = [
  { value: 1, label: "1" },
  { value: 2, label: "2" },
  { value: 3, label: "3" },
  { value: 4, label: "4+" },
];
