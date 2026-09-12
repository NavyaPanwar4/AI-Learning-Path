export default function LoadingSpinner({ message = 'Loading...' }) {
  return (
    <div className="loading-center">
      <div className="spinner" />
      <p style={{ color: 'var(--color-text-muted)', fontWeight: 500 }}>{message}</p>
    </div>
  );
}
