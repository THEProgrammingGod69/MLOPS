import { useState } from "react";
import { Segmented } from "../components/ui";
import Insights from "./Insights";
import Fairness from "./Fairness";

export default function TheModel() {
  const [view, setView] = useState<"insights" | "fairness">("insights");
  return (
    <>
      <div className="row-wrap mb-16">
        <Segmented label="Model section" value={view} onChange={setView} options={[{ value: "insights", label: "Performance" }, { value: "fairness", label: "Fairness" }]} />
      </div>
      {view === "insights" ? <Insights /> : <Fairness />}
    </>
  );
}
