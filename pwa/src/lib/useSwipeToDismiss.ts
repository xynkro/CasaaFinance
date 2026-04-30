import { useRef, useState } from "react";
import type { TouchEvent, CSSProperties } from "react";

// iOS spring curve — same as `--spring`/.modal-fade-in in index.css
const SPRING_CURVE = "cubic-bezier(0.32, 0.72, 0, 1)";
const TRANSITION_MS = 250;
// Direction-lock threshold — small horizontal motion before we commit to a swipe
const LOCK_PX = 10;

interface SwipeToDismissOptions {
  /** Pixels to drag before triggering close. Default 80. */
  threshold?: number;
  /** dragX → backdrop opacity coefficient (default 0.3 of full window width). */
  opacityCoeff?: number;
  /** Swipe axis. Currently only "x" is implemented (horizontal right-swipe). */
  axis?: "x" | "y";
  /** Called when the user releases past the threshold. */
  onDismiss: () => void;
}

interface SwipeToDismissResult {
  /** Current drag offset in px (0 when idle). */
  dragX: number;
  /** True while a touch gesture is in progress (after direction-lock). */
  moving: boolean;
  /** Apply to the modal panel — owns transform + transition. */
  panelStyle: CSSProperties;
  /** Apply to the backdrop — owns opacity that fades during drag. */
  backdropStyle: CSSProperties;
  /** Spread onto the swipeable element. */
  handlers: {
    onTouchStart: (e: TouchEvent) => void;
    onTouchMove: (e: TouchEvent) => void;
    onTouchEnd: (e: TouchEvent) => void;
    onTouchCancel: (e: TouchEvent) => void;
  };
}

/**
 * Swipe-to-dismiss gesture for full-screen modals / sheets.
 *
 * Owns:
 *  - dragX (in useState — render input)
 *  - moving (in useState — kills the React 19 "ref-during-render" lint error
 *    that fires when reading touchRef.current.moving from JSX style)
 *  - touchRef holds *only* start coords (touch state, never read during render)
 *
 * Spreads `{...handlers}` onto the swipeable element. Apply `panelStyle` for
 * the slide-out transform and `backdropStyle` for the fade.
 */
export function useSwipeToDismiss(opts: SwipeToDismissOptions): SwipeToDismissResult {
  const {
    threshold = 80,
    opacityCoeff = 0.3,
    axis = "x",
    onDismiss,
  } = opts;

  const [dragX, setDragX] = useState(0);
  const [moving, setMoving] = useState(false);
  const touchRef = useRef<{ startX: number; startY: number; startTime: number }>({
    startX: 0,
    startY: 0,
    startTime: 0,
  });
  // Captures whether the current gesture has direction-locked into a swipe.
  // Held in a ref because it must update synchronously across handlers within
  // the same gesture (a setState would lag behind onTouchMove).
  const lockedRef = useRef(false);

  const reset = () => {
    setDragX(0);
    setMoving(false);
    lockedRef.current = false;
  };

  const onTouchStart = (e: TouchEvent) => {
    const t = e.touches[0];
    touchRef.current = {
      startX: t.clientX,
      startY: t.clientY,
      startTime: Date.now(),
    };
    lockedRef.current = false;
    setMoving(false);
    setDragX(0);
  };

  const onTouchMove = (e: TouchEvent) => {
    const t = e.touches[0];
    const dx = t.clientX - touchRef.current.startX;
    const dy = t.clientY - touchRef.current.startY;

    if (axis === "x") {
      // Direction-lock: if user moves vertically more than horizontally, or
      // swipes left, bail out so the page can scroll.
      if (!lockedRef.current) {
        if (Math.abs(dy) > Math.abs(dx)) return;
        if (Math.abs(dx) < LOCK_PX) return;
        if (dx <= 0) return;
        lockedRef.current = true;
        setMoving(true);
      }
      if (dx > 0) {
        // Clamp to viewport width — beyond that the modal would translate
        // past the screen edge and dragX would keep ballooning.
        const clamped = Math.min(dx, window.innerWidth);
        setDragX(clamped);
      }
    } else {
      // Vertical: same logic mirrored on dy. Currently no caller uses this,
      // but the option is wired for future bottom-sheets.
      if (!lockedRef.current) {
        if (Math.abs(dx) > Math.abs(dy)) return;
        if (Math.abs(dy) < LOCK_PX) return;
        if (dy <= 0) return;
        lockedRef.current = true;
        setMoving(true);
      }
      if (dy > 0) {
        const clamped = Math.min(dy, window.innerHeight);
        setDragX(clamped);
      }
    }
  };

  const onTouchEnd = () => {
    if (lockedRef.current && dragX >= threshold) {
      onDismiss();
      // Don't reset dragX — let the modal unmount mid-slide so the user sees
      // it leave the screen rather than snapping back first.
      setMoving(false);
      lockedRef.current = false;
    } else {
      reset();
    }
  };

  const onTouchCancel = () => {
    reset();
  };

  // ── derived styles ───────────────────────────────────────────────────────
  // Reading `moving` (state, not ref) keeps this hook lint-clean.
  const transitionProp = axis === "x" ? "transform" : "transform";
  const panelStyle: CSSProperties = {
    transform: axis === "x" ? `translateX(${dragX}px)` : `translateY(${dragX}px)`,
    transition: moving ? "none" : `${transitionProp} ${TRANSITION_MS}ms ${SPRING_CURVE}`,
  };

  // Backdrop opacity fades from 1 → (1 - opacityCoeff) across one full
  // viewport. windowWidth is read at render time — fine for our use because
  // the device doesn't rotate mid-gesture.
  const viewportSize = axis === "x"
    ? (typeof window !== "undefined" ? window.innerWidth : 1)
    : (typeof window !== "undefined" ? window.innerHeight : 1);
  const backdropStyle: CSSProperties = {
    opacity: 1 - Math.min(dragX / viewportSize, 1) * opacityCoeff,
  };

  return {
    dragX,
    moving,
    panelStyle,
    backdropStyle,
    handlers: { onTouchStart, onTouchMove, onTouchEnd, onTouchCancel },
  };
}
