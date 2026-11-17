export default function MarkSchemeTable({ questionRef, markScheme }) {
  if (!markScheme) return null;
  const levels = markScheme.levels || [];
  const indicative = markScheme.indicative_content;

  return (
    <section className="panel mark-scheme-panel">
      <header className="panel-header">
        <h2>Mark scheme</h2>
      </header>
      <div className="panel-body mark-scheme-table-wrap">
        <table className="mark-scheme-table">
          <thead>
            <tr>
              <th scope="col">Question</th>
              <th scope="col">Answers</th>
              <th scope="col">Mark</th>
            </tr>
          </thead>
          <tbody data-baseline-tour="mark-scheme-levels">
            {levels.map((level, index) => (
              <tr key={level.label}>
                {index === 0 ? (
                  <th scope="rowgroup" rowSpan={levels.length || 1} className="mark-scheme-question-cell">
                    {questionRef ? questionRef : "—"}
                  </th>
                ) : null}
                <td className="mark-scheme-answers-cell">
                  <strong>{level.label}</strong>
                  {level.descriptor ? <p>{level.descriptor}</p> : null}
                </td>
                <td className="mark-scheme-mark-cell">{level.mark || ""}</td>
              </tr>
            ))}
          </tbody>
          {indicative ? (
            <tbody data-baseline-tour="mark-scheme-indicative">
              <tr className="mark-scheme-indicative-row">
                <th scope="row" className="mark-scheme-question-cell" />
                <td className="mark-scheme-answers-cell">
                  <p>
                    <strong>Indicative content</strong>
                  </p>
                  {(indicative.themes || []).map((theme) => (
                    <div key={theme.title || "theme"} className="mark-scheme-theme">
                      {theme.title ? <p className="mark-scheme-theme-title">{theme.title}</p> : null}
                      <ul className="mark-scheme-bullets">
                        {(theme.items || []).map((item) => (
                          <li key={item.text || item.subitems?.[0]}>
                            <span>{item.text}</span>
                            {item.subitems?.length ? (
                              <ul className="mark-scheme-subbullets">
                                {item.subitems.map((sub) => (
                                  <li key={sub}>{sub}</li>
                                ))}
                              </ul>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                  {indicative.footer_note ? (
                    <p className="mark-scheme-footer-note">{indicative.footer_note}</p>
                  ) : null}
                </td>
                <td className="mark-scheme-mark-cell" />
              </tr>
            </tbody>
          ) : null}
        </table>
      </div>
    </section>
  );
}
