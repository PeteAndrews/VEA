import { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";

import { clearDraft, setDraft, setQuotedSpan } from "../judgementSlice";
import { selectionToOffsets } from "../responseUtils";
import { store } from "../store";
import { setWalkthroughStep, walkthroughRuntime } from "./replay";
import { captureInteractionCheckpoint, restoreInteractionCheckpoint } from "./checkpoint";
import {
  WALKTHROUGH_INTERACTION_COUNT,
  WALKTHROUGH_STEPS,
  selectionCloseEnough,
} from "./steps";

const BLOCKED_EVENTS = ["pointerdown", "mousedown", "click", "dblclick", "contextmenu", "submit", "keydown"];
const SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "PageUp",
  "PageDown",
  "Home",
  "End",
]);

function resolveTargets(step) {
  const selectors = Array.isArray(step.target) ? step.target : [step.target];
  const found = [];
  for (const selector of selectors) {
    if (!selector) continue;
    const element = document.querySelector(selector);
    if (!element) continue;
    found.push(element);
    if (step.spotlight !== "all") break;
  }
  return found;
}

function isAllowed(eventTarget, step) {
  if (!(eventTarget instanceof Element)) return false;
  if (eventTarget.closest(".walkthrough-card")) return true;
  return (step.allow || []).some((selector) => eventTarget.closest(selector));
}

function rectsEqual(current, next) {
  if (current.length !== next.length) return false;
  return current.every((rect, index) => {
    const other = next[index];
    return (
      Math.abs(rect.top - other.top) < 1 &&
      Math.abs(rect.left - other.left) < 1 &&
      Math.abs(rect.width - other.width) < 1 &&
      Math.abs(rect.height - other.height) < 1
    );
  });
}

function emphasizeRects(step) {
  if (!step?.emphasize) return [];
  const selectors = Array.isArray(step.emphasize) ? step.emphasize : [step.emphasize];
  const boxes = [];
  selectors.forEach((selector) => {
    document.querySelectorAll(selector).forEach((element) => {
      const rect = element.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) boxes.push(rect);
    });
  });
  return boxes;
}

function chooseCardClass(step, spotlightRects) {
  const width = Math.min(420, window.innerWidth - 32);
  const height = 210;
  const obstacles = [...spotlightRects];
  if (step.interaction === 10 || step.interaction === 11) {
    const review = document.querySelector(".level-review-panel");
    if (review) obstacles.push(review.getBoundingClientRect());
  }
  const spots = [
    { name: "walkthrough-card-left", left: 16, top: 16 },
    { name: "walkthrough-card-right", left: window.innerWidth - width - 16, top: 16 },
    { name: "walkthrough-card-bottom-left", left: 16, top: window.innerHeight - height - 16 },
    { name: "walkthrough-card-bottom-right", left: window.innerWidth - width - 16, top: window.innerHeight - height - 16 },
  ];
  if (step.interaction !== 10 && step.interaction !== 11) {
    spots.push({
      name: "walkthrough-card-bottom",
      left: (window.innerWidth - width) / 2,
      top: window.innerHeight - height - 16,
    });
  }
  function overlap(spot, rect) {
    const horizontal = Math.max(
      0,
      Math.min(spot.left + width, rect.left + rect.width) - Math.max(spot.left, rect.left)
    );
    const vertical = Math.max(
      0,
      Math.min(spot.top + height, rect.top + rect.height) - Math.max(spot.top, rect.top)
    );
    return horizontal * vertical;
  }
  return spots.reduce((best, spot) => {
    const score = obstacles.reduce((sum, rect) => sum + overlap(spot, rect), 0);
    return score < best.score ? { name: spot.name, score } : best;
  }, { name: spots[0].name, score: Infinity }).name;
}

function continueLabel(step) {
  if (step.continueLabel) return step.continueLabel;
  if (step.phase === "start") return "Start";
  if (step.phase === "end") return "Complete";
  return "Continue";
}

export default function WalkthroughOverlay() {
  const dispatch = useDispatch();
  const draft = useSelector((state) => state.judgement.draft);
  const [index, setIndex] = useState(0);
  const [hint, setHint] = useState("");
  const [rects, setRects] = useState([]);
  const [marks, setMarks] = useState([]);
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  const scrolledFor = useRef(null);
  const focusedFor = useRef(null);
  const checkpoints = useRef(new Map());
  const restoringRef = useRef(false);
  const restartTarget = useRef(null);
  const [restarting, setRestarting] = useState(false);
  const step = WALKTHROUGH_STEPS[index];

  useEffect(() => {
    setWalkthroughStep(step);
  }, [step]);

  useEffect(() => {
    if (!step?.select || !draft?.text) return;
    if (selectionCloseEnough(draft, step.select)) {
      if (draft.start_char !== step.select.start || draft.end_char !== step.select.end) {
        dispatch(
          setDraft({
            start_char: step.select.start,
            end_char: step.select.end,
            text: step.select.text,
          })
        );
      }
      setHint("");
      return;
    }
    setHint(`Not quite — select “${step.select.text}”.`);
    dispatch(clearDraft());
  }, [dispatch, draft, step]);

  useEffect(() => {
    if (!step?.select) return undefined;
    function onMouseUp() {
      const container = document.querySelector(".selectable-response");
      const text = store.getState().marking.selectedResponse?.text || "";
      const offsets = selectionToOffsets(container, window.getSelection(), text);
      if (offsets) dispatch(setDraft(offsets));
    }
    document.addEventListener("mouseup", onMouseUp);
    return () => document.removeEventListener("mouseup", onMouseUp);
  }, [dispatch, step]);

  useEffect(() => {
    let frame = 0;
    const watch = () => {
      const state = store.getState();
      if (restoringRef.current) {
        if (restartTarget.current && step.id === restartTarget.current) {
          restoringRef.current = false;
          restartTarget.current = null;
        } else {
          frame = requestAnimationFrame(watch);
          return;
        }
      }
      if (step.interaction > 6 && store.getState().judgement.quotedSpan) {
        dispatch(setQuotedSpan(null));
        frame = requestAnimationFrame(watch);
        return;
      }
      if (!checkpoints.current.has(step.interaction)) {
        checkpoints.current.set(step.interaction, captureInteractionCheckpoint());
      }
      if (typeof step.done === "function" && step.done(state, walkthroughRuntime())) {
        setHint("");
        setIndex((current) => Math.min(current + 1, WALKTHROUGH_STEPS.length - 1));
        return;
      }
      const nextRects = resolveTargets(step).map((element) => element.getBoundingClientRect());
      const nextMarks = emphasizeRects(step);
      setRects((current) => (rectsEqual(current, nextRects) ? current : nextRects));
      setMarks((current) => (rectsEqual(current, nextMarks) ? current : nextMarks));
      const nextViewport = { width: window.innerWidth, height: window.innerHeight };
      setViewport((current) =>
        current.width === nextViewport.width && current.height === nextViewport.height ? current : nextViewport
      );
      const target = resolveTargets(step)[0];
      if (target && scrolledFor.current !== step.id) {
        target.scrollIntoView({ block: "center", behavior: "smooth" });
        scrolledFor.current = step.id;
      }
      if (step.focus && focusedFor.current !== step.id) {
        const input = document.querySelector(step.focus);
        if (input) {
          input.focus();
          focusedFor.current = step.id;
        }
      }
      frame = requestAnimationFrame(watch);
    };
    frame = requestAnimationFrame(watch);
    return () => cancelAnimationFrame(frame);
  }, [step]);

  useEffect(() => {
    function block(event) {
      if (event.target instanceof Element && event.target.closest(".walkthrough-card")) return;
      if (isAllowed(event.target, step)) return;
      if (event.type === "keydown") {
        if (event.key === "Tab") return;
        if (SCROLL_KEYS.has(event.key)) return;
        if (event.key === " " && !(event.target instanceof Element && event.target.closest("button, a, [role='button']"))) {
          return;
        }
      }
      event.preventDefault();
      event.stopPropagation();
    }
    for (const type of BLOCKED_EVENTS) {
      document.addEventListener(type, block, true);
    }
    return () => {
      for (const type of BLOCKED_EVENTS) {
        document.removeEventListener(type, block, true);
      }
    };
  }, [step]);

  async function restartInteraction() {
    if (restarting) return;
    const start = WALKTHROUGH_STEPS.findIndex((item) => item.interaction === step.interaction);
    const startStep = WALKTHROUGH_STEPS[start < 0 ? 0 : start];
    const checkpoint = checkpoints.current.get(step.interaction);
    setRestarting(true);
    restoringRef.current = true;
    restartTarget.current = startStep.id;
    setHint("");
    try {
      if (checkpoint) await restoreInteractionCheckpoint(checkpoint);
      window.dispatchEvent(new Event("vea-walkthrough-restart"));
    } finally {
      scrolledFor.current = null;
      focusedFor.current = null;
      setIndex(start < 0 ? 0 : start);
      setRestarting(false);
    }
  }

  const cardClass = chooseCardClass(step, rects);

  return (
    <div className="walkthrough-layer">
      <svg
        className="walkthrough-dim"
        viewBox={`0 0 ${viewport.width} ${viewport.height}`}
        preserveAspectRatio="none"
      >
        <defs>
          <mask id="walkthrough-mask">
            <rect width={viewport.width} height={viewport.height} fill="white" />
            {rects.map((rect) => (
              <rect
                key={`${rect.top}-${rect.left}-${rect.width}`}
                x={rect.left - 6}
                y={rect.top - 6}
                width={rect.width + 12}
                height={rect.height + 12}
                rx="8"
                fill="black"
              />
            ))}
          </mask>
        </defs>
        <rect
          width={viewport.width}
          height={viewport.height}
          fill="rgba(15, 23, 42, 0.55)"
          mask="url(#walkthrough-mask)"
        />
      </svg>
      {rects.map((rect) => (
        <div
          key={`${rect.top}-${rect.left}-${rect.width}`}
          className="walkthrough-spotlight"
          style={{ top: rect.top - 6, left: rect.left - 6, width: rect.width + 12, height: rect.height + 12 }}
        />
      ))}
      {marks.map((rect) => (
        <div
          key={`mark-${rect.top}-${rect.left}-${rect.width}`}
          className="walkthrough-spotlight walkthrough-spotlight-mark"
          style={{ top: rect.top - 4, left: rect.left - 4, width: rect.width + 8, height: rect.height + 8 }}
        />
      ))}
      <section
        className={`walkthrough-card ${cardClass}`}
        onMouseDown={(event) => event.nativeEvent.stopPropagation()}
        onPointerDown={(event) => event.nativeEvent.stopPropagation()}
      >
        <p className="walkthrough-kicker">
          Interaction {step.interaction} of {WALKTHROUGH_INTERACTION_COUNT} · {step.title}
        </p>
        <p>{step.instruction}</p>
        {hint ? <p className="walkthrough-hint">{hint}</p> : null}
        {!rects.length && step.done !== "continue" ? <p className="muted">Waiting for the VEA…</p> : null}
        <div className="walkthrough-card-actions">
          {step.done === "continue" ? (
            <button type="button" className="button-primary" onClick={() => setIndex((current) => current + 1)}>
              {continueLabel(step)}
            </button>
          ) : null}
          <button type="button" className="button-secondary" onClick={restartInteraction} disabled={restarting}>
            {restarting ? "Restarting..." : "Restart"}
          </button>
        </div>
      </section>
    </div>
  );
}
