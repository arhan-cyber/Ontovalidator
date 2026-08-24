import { useEffect } from "react";

interface ErrorBannerProps {
  message: string | null;
  onDismiss: () => void;
}

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(onDismiss, 10000);
    return () => window.clearTimeout(timer);
  }, [message, onDismiss]);

  if (!message) return null;

  return (
    <div className="error-banner" role="alert">
      <span>{message}</span>
      <button type="button" className="icon-btn error-banner-dismiss" onClick={onDismiss} aria-label="Dismiss">
        ✕
      </button>
    </div>
  );
}
