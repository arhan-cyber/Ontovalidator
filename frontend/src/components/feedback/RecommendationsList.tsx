interface RecommendationsListProps {
  recommendations: string[];
}

export function RecommendationsList({ recommendations }: RecommendationsListProps) {
  if (!recommendations || recommendations.length === 0) {
    return <p className="hm-empty">No recommendations at this time.</p>;
  }

  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {recommendations.map((rec, i) => (
        <li
          key={i}
          className="card"
          style={{
            display: "flex",
            gap: "0.6rem",
            alignItems: "flex-start",
            fontSize: "0.85rem",
            marginBottom: "0.5rem",
          }}
        >
          <span aria-hidden="true">💡</span>
          <span>{rec}</span>
        </li>
      ))}
    </ul>
  );
}
