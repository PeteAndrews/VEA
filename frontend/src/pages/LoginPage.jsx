import { useState } from "react";

import { useDispatch, useSelector } from "react-redux";

import { useNavigate } from "react-router-dom";

import { startMarkingSession } from "../authSlice";



export default function LoginPage() {

  const dispatch = useDispatch();

  const navigate = useNavigate();

  const { status, error } = useSelector((state) => state.auth);

  const [name, setName] = useState("Alex Parker");



  function handleSubmit(event) {

    event.preventDefault();

    dispatch(

      startMarkingSession({

        name: name.trim() || "Examiner",

        label: "prototype",

      })

    ).then((result) => {

      if (result.meta.requestStatus === "fulfilled") {

        navigate("/questions");

      }

    });

  }



  return (

    <div className="login-page">

      <form className="login-card" onSubmit={handleSubmit}>

        <h1>VEA Marking</h1>

        <p className="muted">Prototype login for examiner access.</p>

        <label htmlFor="name">Examiner name</label>

        <input

          id="name"

          value={name}

          onChange={(event) => setName(event.target.value)}

          placeholder="Your name"

        />

        {error ? <p className="error">{error}</p> : null}

        <button type="submit" disabled={status === "loading"}>

          {status === "loading" ? "Starting session..." : "Continue"}

        </button>

      </form>

    </div>

  );

}


