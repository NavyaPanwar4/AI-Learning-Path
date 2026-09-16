import { useState } from 'react';
import { Link } from 'react-router-dom';
import { FiCompass } from 'react-icons/fi';
import { forgotPassword } from '../api/auth';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await forgotPassword(email);
      setSubmitted(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-center">
      <div className="container-sm auth-container">
        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <div style={{ background: 'var(--color-primary)', color: '#fff', borderRadius: 12, padding: '8px 10px', display: 'flex' }}>
              <FiCompass size={24} />
            </div>
            <h1 style={{ fontSize: '1.8rem', color: 'var(--color-primary)' }}>Learning Path</h1>
          </div>
        </div>

        <div className="card">
          <h2 style={{ marginBottom: 6 }}>Reset your password</h2>
          <p style={{ color: 'var(--color-text-muted)', fontSize: '0.9rem', marginBottom: 28 }}>
            Enter your email and we'll send you a link to reset your password.
          </p>

          {submitted ? (
            <div className="alert" style={{ background: 'var(--color-accent)' }}>
              If an account with that email exists, a reset link has been sent. Check your inbox.
            </div>
          ) : (
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              <div className="input-group">
                <label>Email Address</label>
                <input
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                />
              </div>

              {error && <div className="alert alert-error">{error}</div>}

              <button className="btn btn-primary" type="submit" disabled={loading} style={{ width: '100%', marginTop: 4 }}>
                {loading ? 'Sending...' : 'Send Reset Link →'}
              </button>
            </form>
          )}

          <div style={{ textAlign: 'center', marginTop: 24, paddingTop: 20, borderTop: '1px solid var(--color-accent)' }}>
            <Link to="/login" style={{ color: 'var(--color-primary)', fontWeight: 600, fontSize: '0.9rem' }}>
              ← Back to Login
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}