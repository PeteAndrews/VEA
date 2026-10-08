import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";

import { restoreStudySession } from "./studySlice";
import ControlPlaceholderPage from "./pages/ControlPlaceholderPage";
import LoginPage from "./pages/LoginPage";
import MarkingPage from "./pages/MarkingPage";
import QuestionsPage from "./pages/QuestionsPage";
import StudyMarkingPage from "./pages/StudyMarkingPage";

function RequireStudyLogin({ children }) {
  const participant = useSelector((state) => state.study.participant);
  if (!participant) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  const dispatch = useDispatch();
  const participant = useSelector((state) => state.study.participant);

  useEffect(() => {
    dispatch(restoreStudySession());
  }, [dispatch]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/questions"
        element={
          <RequireStudyLogin>
            <QuestionsPage />
          </RequireStudyLogin>
        }
      />
      <Route
        path="/study/trials/:trialId/mark"
        element={
          <RequireStudyLogin>
            <StudyMarkingPage />
          </RequireStudyLogin>
        }
      />
      <Route
        path="/study/trials/:trialId/control"
        element={
          <RequireStudyLogin>
            <ControlPlaceholderPage />
          </RequireStudyLogin>
        }
      />
      <Route
        path="/mark/:assessmentId/:candidateId"
        element={
          <RequireStudyLogin>
            <MarkingPage />
          </RequireStudyLogin>
        }
      />
      <Route path="/" element={<Navigate to={participant ? "/questions" : "/login"} replace />} />
    </Routes>
  );
}
