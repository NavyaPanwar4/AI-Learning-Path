import { useState, useEffect } from 'react';
import { FiStar, FiMessageSquare, FiExternalLink } from 'react-icons/fi';
import { getUserFeedback } from '../api/roadmap';
import LoadingSpinner from '../components/LoadingSpinner';

export default function MyReviewsPage() {
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchReviews = async () => {
      try {
        const res = await getUserFeedback();
        setReviews(res.data);
      } catch {
        setError('Failed to load reviews.');
      } finally {
        setLoading(false);
      }
    };
    fetchReviews();
  }, []);

  if (loading) return <LoadingSpinner message="Loading your reviews..." />;

  return (
    <div className="page">
      <div className="container">
        <header style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: '1.9rem', marginBottom: 6 }}>My Reviews</h1>
          <p style={{ color: 'var(--color-text-muted)' }}>
            All the materials and resources you've rated
          </p>
        </header>

        {error && (
          <div className="card" style={{ borderColor: 'var(--color-error)', color: 'var(--color-error)', padding: 20, marginBottom: 24 }}>
            {error}
          </div>
        )}

        {reviews.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: 60 }}>
            <FiMessageSquare size={48} style={{ color: 'var(--color-surface-hover)', marginBottom: 16 }} />
            <p style={{ color: 'var(--color-text-muted)' }}>You haven't left any reviews yet.</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 16 }}>
            {reviews.map((rev) => (
              <div key={rev.feedback_id} className="card" style={{ padding: 24 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                  <div>
                    <h3 style={{ marginBottom: 4, fontSize: '1.1rem' }}>
                      {String(rev.content_id).length > 50 ? String(rev.content_id).substring(0, 50) + '...' : rev.content_id}
                    </h3>
                    <span className="badge badge-surface" style={{ textTransform: 'uppercase', fontSize: '0.7rem' }}>{rev.content_type}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 2 }}>
                    {[1, 2, 3, 4, 5].map((s) => (
                      <FiStar
                        key={s}
                        size={16}
                        fill={s <= rev.rating ? '#FDCC0D' : 'none'}
                        color={s <= rev.rating ? '#FDCC0D' : 'var(--color-surface-hover)'}
                      />
                    ))}
                  </div>
                </div>
                {rev.comments && (
                  <p style={{ color: 'var(--color-text-muted)', fontSize: '0.95rem', fontStyle: 'italic', marginBottom: 12 }}>
                    "{rev.comments}"
                  </p>
                )}
                {rev.content_type === 'resource' && typeof rev.content_id === 'string' && rev.content_id.startsWith('http') && (
                  <a href={rev.content_id} target="_blank" rel="noreferrer" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82rem', color: 'var(--color-primary)', fontWeight: 600 }}>
                    <FiExternalLink size={14} /> View Material
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
