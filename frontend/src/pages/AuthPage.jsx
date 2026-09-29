import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { FiCompass, FiEye, FiEyeOff } from 'react-icons/fi';
import { login, register } from '../api/auth';

function getPasswordStrength(pw) {
  if (!pw) return null;
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (score <= 1) return 'weak';
  if (score === 2) return 'medium';
  return 'strong';
}

export default function AuthPage() {
  const navigate = useNavigate();
  const [isLogin, setIsLogin] = useState(true);
  const [form, setForm] = useState({ username: '', email: '', password: '' });
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const strength = !isLogin ? getPasswordStrength(form.password) : null;

  const handleChange = (e) => {
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }));
    setError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isLogin) {
      if (form.username.trim().length < 3) {
        setError('Username must be at least 3 characters.');
        return;
      }
      if (form.password.length < 8 || !/[A-Z]/.test(form.password) || !/[0-9]/.test(form.password)) {
        setError('Password must be at least 8 characters and include one uppercase letter and one number.');
        return;
      }
    }
    setLoading(true);
    setError('');
    try {
      let res;
      if (isLogin) {
        res = await login({ username: form.username, password: form.password });
      } else {
        res = await register({ username: form.username, email: form.email, password: form.password });
      }
      localStorage.setItem('token', res.data.access_token);

      if (isLogin) {
        // Decode JWT to check goal_id (we use a simple heuristic: try to get profile)
        // Since we don't have a /me endpoint, we'll redirect returning users to /roadmap
        // and new users (just registered) always go to /onboarding
        // For login: we redirect to /roadmap, which will bounce back if no profile is set
        navigate('/home');
      } else {
        navigate('/onboarding');
      }
    } catch (err) {
      const msg = err.response?.data?.detail;
      if (Array.isArray(msg)) {
        setError(msg.map((e) => e.msg).join(', '));
      } else {
        setError(msg || 'Something went wrong. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-center">
      <div className="container-sm auth-container">
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <div style={{ background: 'var(--color-primary)', color: '#fff', borderRadius: 12, padding: '8px 10px', display: 'flex' }}>
              <FiCompass size={24} />
            </div>
            <h1 style={{ fontSize: '1.8rem', color: 'var(--color-primary)' }}>Learning Path</h1>
          </div>
          <p style={{ color: 'var(--color-text-muted)', fontSize: '0.95rem' }}>
            Your AI-powered personalized roadmap generator
          </p>
        </div>

        {/* Card */}
        <div className="card">
          <h2 style={{ marginBottom: 6 }}>{isLogin ? 'Welcome back ' : 'Create your account'}</h2>
          <p style={{ color: 'var(--color-text-muted)', fontSize: '0.9rem', marginBottom: 28 }}>
            {isLogin ? 'Sign in to continue your learning journey.' : 'Join thousands building their learning paths.'}
          </p>

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div className="input-group">
              <label>{isLogin ? 'Username or Email' : 'Username'}</label>
              <input
                name="username"
                type="text"
                placeholder={isLogin ? 'Enter your username or email' : 'Choose a username'}
                value={form.username}
                onChange={handleChange}
                required
                autoComplete="username"
              />
            </div>

            {!isLogin && (
              <div className="input-group">
                <label>Email Address</label>
                <input
                  name="email"
                  type="email"
                  placeholder="you@example.com"
                  value={form.email}
                  onChange={handleChange}
                  required
                  autoComplete="email"
                />
              </div>
            )}

            <div className="input-group">
              <label>Password</label>
              <div style={{ position: 'relative' }}>
                <input
                  name="password"
                  type={showPw ? 'text' : 'password'}
                  placeholder={isLogin ? 'Enter your password' : 'Min 8 chars, 1 uppercase, 1 number'}
                  value={form.password}
                  onChange={handleChange}
                  required
                  autoComplete={isLogin ? 'current-password' : 'new-password'}
                  style={{ paddingRight: 44 }}
                />
                <button
                  type="button"
                  onClick={() => setShowPw((v) => !v)}
                  style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }}
                >
                  {showPw ? <FiEyeOff size={18} /> : <FiEye size={18} />}
                </button>
              </div>
              {!isLogin && strength && (
                <>
                  <div className={`strength-bar strength-${strength}`} />
                  <span className="strength-label" style={{ color: strength === 'weak' ? 'var(--color-error)' : strength === 'medium' ? '#e5a020' : 'var(--color-success)' }}>
                    {strength === 'weak' ? 'Weak password' : strength === 'medium' ? 'Medium strength' : '✓ Strong password'}
                  </span>
                </>
              )}
              {isLogin && (
                <div style={{ textAlign: 'right', marginTop: 6 }}>
                  <Link to="/forgot-password" style={{ color: 'var(--color-primary)', fontSize: '0.85rem', fontWeight: 500 }}>
                    Forgot password?
                  </Link>
                </div>
              )}
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            <button className="btn btn-primary" type="submit" disabled={loading} style={{ width: '100%', marginTop: 4 }}>
              {loading ? 'Please wait...' : isLogin ? 'Sign In →' : 'Create Account →'}
            </button>
          </form>

          <div style={{ textAlign: 'center', marginTop: 24, paddingTop: 20, borderTop: '1px solid var(--color-accent)' }}>
            <span style={{ color: 'var(--color-text-muted)', fontSize: '0.9rem' }}>
              {isLogin ? "Don't have an account? " : 'Already have an account? '}
            </span>
            <button
              onClick={() => { setIsLogin((v) => !v); setError(''); setForm({ username: '', email: '', password: '' }); }}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-primary)', fontWeight: 600, fontSize: '0.9rem' }}
            >
              {isLogin ? 'Register →' : '← Back to Login'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
