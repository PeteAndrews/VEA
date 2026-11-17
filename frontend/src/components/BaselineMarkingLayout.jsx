import BaselineQuestionPanel from "./BaselineQuestionPanel";
import BaselineResponsePanel from "./BaselineResponsePanel";
import CommentaryPanel from "./CommentaryPanel";
import MarkSchemeTable from "./MarkSchemeTable";

export default function BaselineMarkingLayout({ materials, response, finalMarkPanel }) {
  const question = materials?.question;
  const markScheme = materials?.mark_scheme;
  const commentary = materials?.commentary;
  const questionRef = question?.question_ref;

  return (
    <div className="marking-page baseline-marking-page">
      <div className="marking-layout baseline-marking-layout">
        <div className="marking-column marking-column-left">
          <BaselineQuestionPanel question={question} />
          <BaselineResponsePanel response={response} />
          {finalMarkPanel}
        </div>
        <div className="marking-column marking-column-center">
          <MarkSchemeTable questionRef={questionRef} markScheme={markScheme} />
        </div>
        <div className="marking-column marking-column-right">
          <CommentaryPanel commentary={commentary} />
        </div>
      </div>
    </div>
  );
}
