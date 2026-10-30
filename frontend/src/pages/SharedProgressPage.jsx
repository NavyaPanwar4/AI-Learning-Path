import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { FiCheckCircle, FiCircle } from 'react-icons/fi';
import LoadingSpinner from '../components/LoadingSpinner';
import { getSharedProgress } from '../api/learning';

export default function SharedProgressPage() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    getSharedProgress(token)
      .then((res) => { if (active) setData(res.data); })
      .catch((err) => {
        if (active) setError(err.response?.status === 404
          ? 'This shared page does not exist or has been turned off.'
          : 'Could not load this page. Please try again later.');
      });
    return () => { active = false; };
  }, [token]);

  if (error) {
    return (
      <div className="page"><div className="container" style={{ maxWidth: 640 }}>
        <div className="alert alert-error" role="alert">{error}</div>
        <p style={{ marginTop: 16 }}><Link to="/">Go to Learning Path Generator</Link></p>
      </div></div>
    );
  }
  if (!data) return <LoadingSpinner message="Loading shared progress..." />;

  const stats = [
    ['Progress', `${data.progress_pct}%`],
    ['Phases done', `${data.phases_completed}/${data.phases_total}`],
    ['Skills mastered', data.skills_mastered],
    ['Day streak', data.day_streak],
    ['Quizzes taken', data.quizzes_taken],
    ['Avg quiz score', data.average_quiz_score == null ? '—' : `${data.average_quiz_score}%`],
  ];

  return (
    <div className="page"><div className="container" style={{ maxWidth: 720 }}>
      <p style={{ color: 'var(--color-text-muted)' }}>{data.learner} is learning</p>
      <h1 style={{ fontSize: '1.9rem', margin: '4px 0 20px' }}>{data.goal_name}</h1>
      <div style={{ height: 10, borderRadius: 6, background: 'var(--color-border)', overflow: 'hidden', marginBottom: 20 }} role="progressbar" aria-valuenow={data.progress_pct} aria-valuemin={0} aria-valuemax={100}>
        <div style={{ width: `${data.progress_pct}%`, height: '100%', background: 'var(--color-primary, #6c63ff)' }} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 24 }}>
        {stats.map(([label, value]) => (
          <div key={label} className="card" style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{value}</div>
            <div style={{ color: 'var(--color-text-muted)', fontSize: '.8rem' }}>{label}</div>
          </div>
        ))}
      </div>
      <section className="card">
        <h2 style={{ fontSize: '1.1rem', marginBottom: 12 }}>Roadmap phases</h2>
        {data.phases.map((phase, index) => (
          <div key={index} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--color-border)' }}>
            {phase.completed ? <FiCheckCircle color="var(--color-success, #22a06b)" /> : <FiCircle color="var(--color-text-muted)" />}
            <span>{phase.title}</span>
          </div>
        ))}
      </section>
      <p style={{ marginTop: 20, color: 'var(--color-text-muted)', fontSize: '.85rem' }}>Build your own personalised roadmap — <Link to="/">Learning Path Generator</Link></p>
    </div></div>
  );
}
