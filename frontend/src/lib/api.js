import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const URGENCY = {
  Emergency: {
    badge: "bg-red-500/15 text-red-300 border-red-500/50",
    dot: "bg-red-400",
    bar: "bg-red-500",
    label: "Immediate action — call 108",
  },
  Urgent: {
    badge: "bg-amber-500/15 text-amber-300 border-amber-500/50",
    dot: "bg-amber-400",
    bar: "bg-amber-500",
    label: "Care within a few hours",
  },
  Routine: {
    badge: "bg-emerald-500/15 text-emerald-300 border-emerald-500/50",
    dot: "bg-emerald-400",
    bar: "bg-emerald-500",
    label: "Dispensary / OPD in 1-3 days",
  },
  "Self-care": {
    badge: "bg-sky-500/15 text-sky-300 border-sky-500/50",
    dot: "bg-sky-400",
    bar: "bg-sky-500",
    label: "Home care and monitoring",
  },
};

export const urgencyStyle = (level) => URGENCY[level] || URGENCY.Routine;
