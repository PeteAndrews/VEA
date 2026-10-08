import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import { createMarkingSession } from "./api";



const STORAGE_KEY = "vea-auth";



function loadAuth() {

  try {

    const raw = localStorage.getItem(STORAGE_KEY);

    return raw ? JSON.parse(raw) : { user: null, markingSessionId: null };

  } catch {

    return { user: null, markingSessionId: null };

  }

}



function persistAuth(state) {

  localStorage.setItem(

    STORAGE_KEY,

    JSON.stringify({

      user: state.user,

      markingSessionId: state.markingSessionId,

    })

  );

}



export const startMarkingSession = createAsyncThunk(

  "auth/startMarkingSession",

  async ({ name, label }) => {

    const session = await createMarkingSession(name, label);

    return {

      user: { name },

      markingSessionId: session.marking_session_id,

    };

  }

);



const initial = loadAuth();



const authSlice = createSlice({

  name: "auth",

  initialState: {

    user: initial.user,

    markingSessionId: initial.markingSessionId,

    status: "idle",

    error: null,

  },

  reducers: {

    logout(state) {

      state.user = null;

      state.markingSessionId = null;

      state.status = "idle";

      state.error = null;

      localStorage.removeItem(STORAGE_KEY);

    },

    setTrialMarkingSession(state, action) {

      state.markingSessionId = action.payload;

    },

  },

  extraReducers: (builder) => {

    builder

      .addCase(startMarkingSession.pending, (state) => {

        state.status = "loading";

        state.error = null;

      })

      .addCase(startMarkingSession.fulfilled, (state, action) => {

        state.status = "succeeded";

        state.user = action.payload.user;

        state.markingSessionId = action.payload.markingSessionId;

        persistAuth(state);

      })

      .addCase(startMarkingSession.rejected, (state, action) => {

        state.status = "failed";

        state.error = action.error.message;

      });

  },

});



export const { logout, setTrialMarkingSession } = authSlice.actions;

export default authSlice.reducer;


