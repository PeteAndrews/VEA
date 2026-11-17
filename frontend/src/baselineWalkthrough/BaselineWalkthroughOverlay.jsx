import { useEffect, useRef, useState } from "react";

import { BASELINE_WALKTHROUGH_STEPS } from "./steps";

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

function resolveTarget(step) {
  if (!step?.target) return [];
  const element = document.querySelector(step.target);
  return element ? [element] : [];
}

function isAllowed(eventTarget, step) {
  if (!(eventTarget instanceof Element)) return false;
  if (eventTarget.closest(".walkthrough-card")) return true;
  const targets = resolveTarget(step);
  if (targets.some((element) => element.contains(eventTarget))) return true;
  if (step.allowAllPanels) {
    if (eventTarget.closest('[data-baseline-tour]')) return true;
    if (eventTarget.closest(".marking-column")) return true;
  }
  const allowed = step.allow || [];
  if (allowed.some((selector) => eventTarget.closest(selector))) return true;
  if (step.advance === "submit") {
    return Boolean(
      eventTarget.closest('[data-baseline-tour="final-mark-submit"]') ||
        eventTarget.closest('[data-baseline-tour="final-mark"]') ||
        eventTarget.closest("#final-mark")
    );
  }
  return false;
}

function anchorCardToResponse() {
  const response = document.querySelector('[data-baseline-tour="response"]');
  if (!response) {
    return { left: 16, bottom: 16 };
  }
  const rect = response.getBoundingClientRect();
  const cardWidth = Math.min(420, window.innerWidth - 32);
  let left = rect.left;
  const bottom = Math.max(12, window.innerHeight - rect.bottom);
  const maxLeft = window.innerWidth - cardWidth - 12;
  left = Math.min(Math.max(12, left), maxLeft);
  return { left, bottom };
}

export default function BaselineWalkthroughOverlay({ submitting = false }) {
  const [index, setIndex] = useState(0);
  const [spotlightRects, setSpotlightRects] = useState([]);
  const [cardPosition, setCardPosition] = useState(() => anchorCardToResponse());
  const [hint, setHint] = useState("");
  const layerRef = useRef(null);
  const step = BASELINE_WALKTHROUGH_STEPS[index];

  useEffect(() => {
    function measure() {
      const targets = resolveTarget(step);
      targets.forEach((element) => {
        element.scrollIntoView({ block: "nearest", inline: "nearest" });
      });
      setSpotlightRects(
        targets.map((element) => element.getBoundingClientRect()).filter((rect) => rect.width > 0 && rect.height > 0)
      );
      setCardPosition(anchorCardToResponse());
    }
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step]);

  useEffect(() => {
    const layer = layerRef.current;
    if (!layer) return undefined;

    function blockEvent(event) {
      if (!step) return;
      if (step.allowScroll && SCROLL_KEYS.has(event.key)) return;
      if (step.allowScroll && ["wheel", "scroll", "touchmove"].includes(event.type)) return;
      if (isAllowed(event.target, step)) return;
      event.preventDefault();
      event.stopPropagation();
    }

    BLOCKED_EVENTS.forEach((name) => layer.addEventListener(name, blockEvent, true));
    return () => {
      BLOCKED_EVENTS.forEach((name) => layer.removeEventListener(name, blockEvent, true));
    };
  }, [step]);

  function restart() {
    setIndex(0);
    setHint("");
  }

  function next() {
    setHint("");
    if (index < BASELINE_WALKTHROUGH_STEPS.length - 1) {
      setIndex(index + 1);
    }
  }

  const isLast = index === BASELINE_WALKTHROUGH_STEPS.length - 1;
  const showSpotlight = Boolean(step?.target && spotlightRects.length);

  return (
    <div className="walkthrough-layer" ref={layerRef}>
      <div className="walkthrough-dim" aria-hidden="true">
        {showSpotlight ? (
          <svg className="walkthrough-spotlight" width="100%" height="100%">
            <defs>
              <mask id="baseline-walkthrough-mask">
                <rect width="100%" height="100%" fill="white" />
                {spotlightRects.map((rect) => (
                  <rect
                    key={`${rect.top}-${rect.left}`}
                    x={rect.left - 4}
                    y={rect.top - 4}
                    width={rect.width + 8}
                    height={rect.height + 8}
                    rx="8"
                    fill="black"
                  />
                ))}
              </mask>
            </defs>
            <rect width="100%" height="100%" fill="rgba(15, 23, 42, 0.55)" mask="url(#baseline-walkthrough-mask)" />
          </svg>
        ) : (
          <div className="walkthrough-dim-solid" />
        )}
      </div>
      <div
        className="walkthrough-card walkthrough-card-baseline-anchor"
        style={{
          left: cardPosition.left,
          bottom: cardPosition.bottom,
          top: "auto",
          right: "auto",
        }}
      >
        <p className="walkthrough-kicker">
          Step {index + 1} of {BASELINE_WALKTHROUGH_STEPS.length}
        </p>
        <h3>{step?.title}</h3>
        <p>{step?.body}</p>
        {hint ? <p className="walkthrough-hint">{hint}</p> : null}
        <div className="walkthrough-card-actions">
          <button type="button" className="button-secondary" onClick={restart}>
            Restart
          </button>
          {step?.advance === "button" ? (
            <button type="button" className="button-link" onClick={next}>
              {step.continueLabel || (isLast ? "Finish" : "Continue")}
            </button>
          ) : (
            <p className="muted">{submitting ? "Submitting..." : "Use Submit mark on the form when ready."}</p>
          )}
        </div>
      </div>
    </div>
  );
}
