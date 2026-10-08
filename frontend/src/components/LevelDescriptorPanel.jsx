import { useDispatch, useSelector } from "react-redux";
import { showLevelInterventionCard } from "../levelAiSlice";
import { setTentativeLevel } from "../judgementSlice";
import LevelInterventionCard from "./LevelInterventionCard";

function levelClass(level) {
  if (level === 3) return "level-card level-3";
  if (level === 2) return "level-card level-2";
  if (level === 1) return "level-card level-1";
  return "level-card level-0";
}

function rangeLabel(markRange) {
  if (!markRange) return "0";
  if (markRange.min === markRange.max) return String(markRange.min);
  return `${markRange.min}-${markRange.max}`;
}

export default function LevelDescriptorPanel({ assessmentId, candidateId, levels }) {
  const dispatch = useDispatch();
  const { markingSessionId } = useSelector((state) => state.auth);
  const { tentativeLevel, saving } = useSelector((state) => state.judgement);
  const { interpretation, checking, activeCard } = useSelector((state) => state.levelAi);

  if (!levels?.length) return null;

  const selectedLevel = tentativeLevel?.level;
  const levelInterpretation =
    selectedLevel != null && interpretation?.level === selectedLevel ? interpretation : null;

  function handleLevelClick(level) {
    const nextLevel = tentativeLevel?.level === level ? null : level;
    dispatch(
      setTentativeLevel({
        markingSessionId,
        assessmentId,
        candidateId,
        level: nextLevel,
      })
    );
  }

  function showInterventionBadge() {
    return (
      levelInterpretation?.intervention?.type &&
      levelInterpretation.status === "pending" &&
      !activeCard
    );
  }

  return (
    <section className="panel panel-wide level-descriptor-panel">
      <header className="panel-header">
        <h2>Level Descriptor</h2>
        <span className="muted">Click a level to set tentative mark band</span>
        {checking ? <span className="checking-dot" title="Checking level" /> : null}
      </header>
      <div className="panel-body level-grid">
        {levels.map((level) => {
          const selected = selectedLevel === level.level;
          const showCard =
            selected &&
            activeCard &&
            levelInterpretation?.status === "pending" &&
            levelInterpretation?.intervention;

          return (
            <article
              key={level.level}
              className={`${levelClass(level.level)}${selected ? " selected" : ""}${
                saving ? " disabled" : ""
              }`}
              onClick={() => !saving && handleLevelClick(level.level)}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  handleLevelClick(level.level);
                }
              }}
            >
              <div className="level-card-top">
                <h3>{level.label}</h3>
                <span className="mark-badge">{rangeLabel(level.mark_range)}</span>
              </div>
              <p>{level.text}</p>
              <div className="level-tags">
                {selected ? <span className="tag tag-tentative">Tentative</span> : null}
                {selected && showInterventionBadge() ? (
                  <button
                    type="button"
                    className={`intervention-badge intervention-${levelInterpretation.intervention.type.toLowerCase()}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      dispatch(showLevelInterventionCard());
                    }}
                  >
                    {levelInterpretation.intervention.type}
                  </button>
                ) : null}
                {level.mark_range_source ? (
                  <span
                    className="tag tag-corrected"
                    title={`Corrected from ${level.mark_range_source.min}-${level.mark_range_source.max}. ${level.provenance?.reason || ""}`}
                  >
                    Corrected
                  </span>
                ) : null}
                {level.source === "fallback" ? (
                  <span className="tag tag-default" title={level.provenance?.note}>
                    Default
                  </span>
                ) : null}
              </div>
              {showCard ? (
                <LevelInterventionCard
                  assessmentId={assessmentId}
                  candidateId={candidateId}
                  interpretation={levelInterpretation}
                  inline
                />
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
