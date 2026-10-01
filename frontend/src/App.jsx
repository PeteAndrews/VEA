import { Navigate, Route, Routes } from "react-router-dom";
import { useSelector } from "react-redux";
import LoginPage from "./pages/LoginPage";
import MarkingPage from "./pages/MarkingPage";
import QuestionsPage from "./pages/QuestionsPage";

function RequireLogin({ children }) {
  const { user, markingSessionId } = useSelector((state) => state.auth);
  if (!user || !markingSessionId) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  const user = useSelector((state) => state.auth.user);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/questions"
        element={
          <RequireLogin>
            <QuestionsPage />
          </RequireLogin>
        }
      />
      <Route
        path="/mark/:assessmentId/:candidateId"
        element={
          <RequireLogin>
            <MarkingPage />
          </RequireLogin>
        }
      />
      <Route path="/" element={<Navigate to={user ? "/questions" : "/login"} replace />} />
    </Routes>
  );
}
