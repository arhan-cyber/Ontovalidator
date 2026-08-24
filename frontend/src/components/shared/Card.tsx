import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  error?: string | null;
  loading?: boolean;
  children?: ReactNode;
}

export function Card({ title, error, loading, children, className, ...rest }: CardProps) {
  return (
    <div className={`card${className ? ` ${className}` : ""}`} {...rest}>
      {title ? <h3 className="card-title">{title}</h3> : null}
      {error ? <ErrorInline message={error} /> : null}
      {loading ? <span className="loading">Loading…</span> : null}
      {children}
    </div>
  );
}

function ErrorInline({ message }: { message: string }) {
  return <p className="card-error" role="alert">{message}</p>;
}
