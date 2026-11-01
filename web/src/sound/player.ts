import type { SoundSettings } from "../api/types";

// FR-1.13: move sounds from local files (web/public/sounds, credits in CREDITS.md there).
// - Off means silent: no Audio element is created and nothing is fetched.
// - A new sound cuts the previous one off; nothing queues, and nothing waits for a sound.
// - Which sound a move makes is decided in Python (core/move_sounds.py) and arrives with the move.

export type MoveSound = "move" | "capture" | "check" | "checkmate" | "castle";
export type SoundEvent = MoveSound | "solved" | "failed";

const FILES: Record<SoundEvent, string> = {
  move: "Move",
  capture: "Capture",
  check: "Check",
  checkmate: "Checkmate",
  castle: "Move", // none of the bundled sets has a castling sound
  solved: "Victory",
  failed: "Defeat",
};

/** A short pause so "solved" or "failed" follows the move sound instead of cutting it off at once. */
export const RESULT_DELAY_MS = 250;

class SoundPlayer {
  private settings: SoundSettings = { on: false, volume: 70, set: "sfx" };
  private cache = new Map<string, HTMLAudioElement>();
  private current: HTMLAudioElement | null = null;

  configure(settings: SoundSettings) {
    this.settings = settings;
    if (!settings.on) this.stop();
  }

  url(event: SoundEvent, set = this.settings.set): string {
    return `${import.meta.env.BASE_URL}sounds/${set}/${FILES[event]}.ogg`;
  }

  play(event: SoundEvent | null | undefined) {
    if (!event || !this.settings.on) return;
    const src = this.url(event);
    let audio = this.cache.get(src);
    if (!audio) {
      audio = new Audio(src);
      audio.preload = "auto";
      this.cache.set(src, audio);
    }
    this.stop();
    audio.volume = Math.min(Math.max(this.settings.volume / 100, 0), 1);
    audio.currentTime = 0;
    this.current = audio;
    // Never let a sound block or break the board: a refused play (autoplay policy) is just silence.
    audio.play().catch(() => undefined);
  }

  later(event: SoundEvent | null | undefined, ms = RESULT_DELAY_MS) {
    if (!event || !this.settings.on) return;
    window.setTimeout(() => this.play(event), ms);
  }

  stop() {
    if (this.current) {
      this.current.pause();
      this.current = null;
    }
  }
}

export const sounds = new SoundPlayer();
