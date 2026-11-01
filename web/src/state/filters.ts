import type { FilterSpec } from "../api/types";

// The defaults match core/filters.py FilterSpec(): every puzzle, a queue of 20.
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
    min_popularity: null,
    min_plays: null,
    exclude_solved_here: false,
    exclude_played_on_lichess: false,
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
