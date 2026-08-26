import type { RetrievalPathway } from "../../api/types";
import { detailAtLeast, useDetailLevel } from "../../context/DetailLevelContext";
import { FusionGauge, PathwayMiniBars } from "../charts";

interface RetrievalPathwayViewProps {
  pathway?: RetrievalPathway | null;
}

const RETRIEVERS = ["lexical", "semantic", "graph"] as const;

export function RetrievalPathwayView({ pathway }: RetrievalPathwayViewProps) {
  const { level } = useDetailLevel();
  const showReasons = detailAtLeast(level, "trace");
  if (!pathway) return null;

  return (
    <div className="pathway-cols">
      {RETRIEVERS.map((name) => {
        const r = pathway[name];
        const retrieved = typeof r?.score === "number" || typeof r?.rank === "number";
        return (
          <div className="pathway-col" key={name}>
            <h5>{name}</h5>
            <PathwayMiniBars score={r?.score ?? null} />
            {retrieved ? (
              <>
                <div>rank: {r.rank ?? "—"}</div>
                <div>score: {r.score ?? "—"}</div>
                {showReasons ? <div style={{ fontSize: "0.74rem" }}>{r.reason}</div> : null}
              </>
            ) : (
              <span className="not-retrieved">not retrieved</span>
            )}
          </div>
        );
      })}
      <div style={{ gridColumn: "1 / -1" }}>
        <FusionGauge score={pathway.fusion_score} explanation={pathway.fusion_explanation} />
        {pathway.retriever_sources?.length ? (
          <span style={{ fontSize: "0.72rem", color: "var(--gray)" }}>
            sources: {pathway.retriever_sources.join(", ")}
          </span>
        ) : null}
      </div>
    </div>
  );
}
