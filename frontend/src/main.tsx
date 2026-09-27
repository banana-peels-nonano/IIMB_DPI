import React from "react";
import ReactDOM from "react-dom/client";
import "ux4g-web-components/styles.css";
import "ux4g-web-components/design-system";
import App from "./App";
import "./styles/app.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
