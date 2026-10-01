import { configureStore } from "@reduxjs/toolkit";
import authReducer from "./authSlice";
import assessmentsReducer from "./assessmentsSlice";
import judgementReducer from "./judgementSlice";
import markingReducer from "./markingSlice";

export const store = configureStore({
  reducer: {
    auth: authReducer,
    assessments: assessmentsReducer,
    marking: markingReducer,
    judgement: judgementReducer,
  },
});
