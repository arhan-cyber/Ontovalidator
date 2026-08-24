import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Render error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="error-banner" role="alert">
          <span>Something went wrong: {this.state.error.message}</span>
          <button
            type="button"
            className="icon-btn"
            onClick={() => this.setState({ error: null })}
          >
            ✕
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
