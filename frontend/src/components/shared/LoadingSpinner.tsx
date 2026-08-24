interface LoadingSpinnerProps {
  message?: string;
}

export function LoadingSpinner({ message = "Loading…" }: LoadingSpinnerProps) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}
