import React from 'react';
import { AlertTriangle } from 'lucide-react';

interface State {
  error: Error | null;
}

/** Keeps one broken screen from blanking the whole app. */
export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error('Screen failed to render', error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="card card-pad flex flex-col items-center text-center">
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-2xl bg-feedback-error-bg text-feedback-error">
          <AlertTriangle size={22} />
        </div>
        <p className="t-card">This screen could not be shown</p>
        <p className="mt-1 text-sm text-ctText-muted">Reload the page. If it keeps happening, tell your teacher or administrator.</p>
        <button type="button" className="btn btn-secondary btn-sm mt-4" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
