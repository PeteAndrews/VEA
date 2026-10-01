export default function LevelContextPanel({ levelContext }) {

  if (!levelContext) return null;



  return (

    <section className="panel panel-wide">

      <header className="panel-header">

        <h2>Tentative Level Context</h2>

        <span className="badge">

          {levelContext.label} ({levelContext.mark_range?.min}-{levelContext.mark_range?.max})

        </span>

      </header>

      <div className="panel-body level-context-body">

        <p>{levelContext.text}</p>

        {levelContext.rules?.length ? (

          <div>

            <h3>Rules</h3>

            <ul>

              {levelContext.rules.map((rule) => (

                <li key={rule}>{rule}</li>

              ))}

            </ul>

          </div>

        ) : null}

        {levelContext.required_criteria?.length ? (

          <div>

            <h3>Required criteria</h3>

            <ul className="required-list">

              {levelContext.required_criteria.map((item) => (

                <li key={item.criterion_id}>

                  <span>{item.criterion_text}</span>

                  <span className="muted">

                    {item.coding_ids.length

                      ? `${item.coding_ids.length} linked coding(s)`

                      : "No linked codings"}

                  </span>

                </li>

              ))}

            </ul>

          </div>

        ) : null}

      </div>

    </section>

  );

}


