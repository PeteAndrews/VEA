import { useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";

import { openStudySession } from "../studySlice";

export default function LoginPage() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const { status, error } = useSelector((state) => state.study);
  const [token, setToken] = useState("");

  function handleSubmit(event) {
    event.preventDefault();
    dispatch(openStudySession({ token: token.trim() })).then((result) => {
      if (result.meta.requestStatus === "fulfilled") {
        navigate("/questions");
      }
    });
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>VEA Study</h1>
        <p className="muted">Enter your study token to continue.</p>
        <label htmlFor="token">Study token</label>
        <input
          id="token"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Paste your token"
          autoComplete="off"
        />
        {error ? <p className="error">{error}</p> : null}
        <button type="submit" disabled={status === "loading" || !token.trim()}>
          {status === "loading" ? "Checking token..." : "Continue"}
        </button>
      </form>
    </div>
  );
}
