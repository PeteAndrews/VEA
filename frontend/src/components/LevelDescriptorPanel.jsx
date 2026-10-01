import { useDispatch, useSelector } from "react-redux";

import { setTentativeLevel } from "../judgementSlice";



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



  if (!levels?.length) return null;



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



  return (

    <section className="panel panel-wide">

      <header className="panel-header">

        <h2>Level Descriptor (Mark Scheme)</h2>

        <span className="muted">Click a level to set tentative mark band</span>

      </header>

      <div className="panel-body level-grid">

        {levels.map((level) => {

          const selected = tentativeLevel?.level === level.level;

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

            </article>

          );

        })}

      </div>

      <footer className="panel-footer panel-note">

        Indicative content is used to support judgement but does not automatically determine the level.

      </footer>

    </section>

  );

}


