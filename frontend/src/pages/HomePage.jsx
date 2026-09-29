import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FiArrowRight, FiPlus, FiMap, FiStar, FiMessageSquare, FiClock, FiZap,
  FiAward, FiCheckCircle, FiTarget, FiAlertCircle, FiCircle,
} from 'react-icons/fi';
import { getDashboard } from '../api/user';
import LoadingSpinner from '../components/LoadingSpinner';

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

function today() {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric',
  });
}

export default function HomePage() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    getDashboard()
      .then((res) => setDashboard(res.data))
      .catch(() => setError('Could not load your dashboard. Is your backend running?'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <LoadingSpinner message="Loading your dashboard..." />;
  if (error) return <div className="page"><div className="container"><div className="alert alert-error">{error}</div></div></div>;

  const { profile, goals, skills_mastery, skill_buckets, quote, stats } = dashboard;

  // "Pick up where you left off" — most recently started goal that isn't finished yet.
  const inProgress = [...goals]
    .filter((g) => !g.is_complete)
    .sort((a, b) => new Date(b.started_at || 0) - new Date(a.started_at || 0));
  const continueGoal = inProgress[0] || null;

  return (
    <div className="page">
      <div style={{ maxWidth: 1100, margin: '0 auto' }}>

        <div style={{ marginBottom: 28 }}>
          <div style={{ color: 'var(--color-text-muted)', fontSize: '.85rem', marginBottom: 4 }}>{today()}</div>
          <h1 style={{ fontSize: '2rem' }}>{greeting()}, {profile.username} 👋</h1>
        </div>

        {/* Pick up where you left off */}
        <div className="card" style={{ marginBottom: 24 }}>
          {continueGoal ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
                <div>
                  <div style={{ color: 'var(--color-text-muted)', fontSize: '.78rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: .4, marginBottom: 6 }}>
                    Pick up where you left off
                  </div>
                  <h2 style={{ fontSize: '1.35rem' }}>{continueGoal.goal_name}</h2>
                </div>
                <button className="btn btn-primary" onClick={() => navigate(`/roadmap/${continueGoal.goal_id}`)}>
                  Continue Learning <FiArrowRight size={16} />
                </button>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 10, alignItems: 'center', marginBottom: 10 }}>
                <div style={{ height: 8, borderRadius: 999, background: '#e7e6df', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${continueGoal.progress_pct}%`, background: 'var(--color-accent)', borderRadius: 'inherit' }} />
                </div>
                <span style={{ fontSize: '.82rem', fontWeight: 700, color: 'var(--color-text-muted)' }}>{continueGoal.progress_pct}%</span>
              </div>
              <div style={{ fontSize: '.8rem', color: 'var(--color-text-muted)' }}>
                {continueGoal.skills_completed} / {continueGoal.skills_total} skills completed
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '20px 0' }}>
              <h2 style={{ fontSize: '1.3rem', marginBottom: 8 }}>You don't have an active learning path yet</h2>
              <p style={{ color: 'var(--color-text-muted)', marginBottom: 18 }}>Pick a goal and get a personalized roadmap in minutes.</p>
              <button className="btn btn-primary" onClick={() => navigate('/onboarding')}>
                Start a Learning Goal <FiArrowRight size={16} />
              </button>
            </div>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 24, alignItems: 'start', marginBottom: 24 }}>
          {/* Skills snapshot */}
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FiTarget color="var(--color-accent)" /> Your Skills</h3>
              <button className="btn btn-ghost" style={{ minHeight: 'auto', padding: 0, fontSize: '.8rem', color: 'var(--color-accent)' }} onClick={() => navigate('/my-skills')}>
                View All
              </button>
            </div>

            {skills_mastery.length === 0 ? (
              <p style={{ color: 'var(--color-text-muted)', fontSize: '.88rem' }}>No skills recorded yet — start a learning goal to begin tracking them.</p>
            ) : (
              <div style={{ display: 'grid', gap: 10, marginBottom: 16 }}>
                {skills_mastery.slice(0, 5).map((s) => (
                  <div key={s.skill_name} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 38px', gap: 10, alignItems: 'center' }}>
                    <span style={{ fontSize: '.82rem', fontWeight: 600 }}>{s.skill_name}</span>
                    <div style={{ height: 7, borderRadius: 999, background: '#e7e6df', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${s.mastery_pct}%`, borderRadius: 'inherit', background: 'var(--color-accent)' }} />
                    </div>
                    <span style={{ fontSize: '.78rem', color: 'var(--color-text-muted)', textAlign: 'right' }}>{s.mastery_pct}%</span>
                  </div>
                ))}
              </div>
            )}

            {(skill_buckets.needs_improvement.length > 0 || skill_buckets.not_started.length > 0) && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
                {skill_buckets.needs_improvement.length > 0 && (
                  <div style={{ padding: 12, borderRadius: 10, background: '#fbf1e2' }}>
                    <div style={{ color: '#c7862f', fontWeight: 700, fontSize: '.76rem', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                      <FiAlertCircle size={12} /> Needs Improvement
                    </div>
                    {skill_buckets.needs_improvement.slice(0, 3).map((n) => (
                      <div key={n} style={{ fontSize: '.76rem', color: '#c7862f' }}>{n}</div>
                    ))}
                  </div>
                )}
                {skill_buckets.not_started.length > 0 && (
                  <div style={{ padding: 12, borderRadius: 10, background: '#fdecea' }}>
                    <div style={{ color: '#c0574a', fontWeight: 700, fontSize: '.76rem', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                      <FiCircle size={12} /> Not Started
                    </div>
                    {skill_buckets.not_started.slice(0, 3).map((n) => (
                      <div key={n} style={{ fontSize: '.76rem', color: '#c0574a' }}>{n}</div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Quick stats + quick actions */}
          <div style={{ display: 'grid', gap: 24 }}>
            <div className="card">
              <h3 style={{ marginBottom: 14 }}>At a Glance</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                <MiniStat icon={<FiZap />} value={stats.day_streak} label="Day Streak" color="#e0604f" bg="#fdecea" />
                <MiniStat icon={<FiClock />} value={`${stats.total_learning_time_hours}h`} label="Learning Time" color="#f0a06d" bg="#fdf1e7" />
                <MiniStat icon={<FiCheckCircle />} value={stats.skills_mastered} label="Skills Mastered" color="#4d9e6e" bg="#eaf6ee" />
                <MiniStat icon={<FiAward />} value={stats.learning_paths_completed} label="Paths Completed" color="#c7862f" bg="#fbf1e2" />
              </div>
            </div>

            <div className="card">
              <h3 style={{ marginBottom: 14 }}>Quick Actions</h3>
              <div style={{ display: 'grid', gap: 10 }}>
                <button className="btn btn-outline" style={{ justifyContent: 'flex-start' }} onClick={() => navigate('/onboarding')}>
                  <FiPlus size={15} /> New Learning Goal
                </button>
                <button className="btn btn-outline" style={{ justifyContent: 'flex-start' }} onClick={() => navigate('/saved-roadmaps')}>
                  <FiMap size={15} /> All Learning Paths
                </button>
                <button className="btn btn-outline" style={{ justifyContent: 'flex-start' }} onClick={() => navigate('/my-skills')}>
                  <FiStar size={15} /> My Skills
                </button>
                <button className="btn btn-outline" style={{ justifyContent: 'flex-start' }} onClick={() => navigate('/my-reviews')}>
                  <FiMessageSquare size={15} /> My Reviews
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Quote */}
        <div className="card" style={{ background: 'var(--color-accent-soft)' }}>
          <p style={{ fontStyle: 'italic', color: '#a65241', fontSize: '.9rem', marginBottom: 4 }}>"{quote}"</p>
          <span style={{ fontSize: '.75rem', color: '#a65241', fontWeight: 700 }}>— LearnPath</span>
        </div>
      </div>
    </div>
  );
}

function MiniStat({ icon, value, label, color, bg }) {
  return (
    <div style={{ padding: 12, borderRadius: 12, background: bg }}>
      <div style={{ color, marginBottom: 6 }}>{icon}</div>
      <div style={{ fontSize: '1.15rem', fontWeight: 800, color: '#333' }}>{value}</div>
      <div style={{ fontSize: '.72rem', color: 'var(--color-text-muted)' }}>{label}</div>
    </div>
  );
}
