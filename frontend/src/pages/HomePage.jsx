import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FiActivity, FiAlertCircle, FiArrowRight, FiAward, FiBookOpen, FiCalendar,
  FiCheckCircle, FiChevronRight, FiCircle, FiClock, FiMap, FiMessageSquare,
  FiPlus, FiStar, FiTarget, FiTrendingUp, FiZap,
} from 'react-icons/fi';
import { getDashboard, getDashboardActivity } from '../api/user';
import { getReminders, getReviewQueue } from '../api/learning';
import LoadingSpinner from '../components/LoadingSpinner';
import '../styles/overview-dashboard.css';

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

function today() {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric',
  });
}

function dateLabel(value, includeTime = false) {
  if (!value) return 'Date unavailable';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Date unavailable';
  return parsed.toLocaleString(undefined, includeTime
    ? { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }
    : { month: 'short', day: 'numeric' });
}

function formatMinutes(value) {
  const minutes = Math.max(0, Math.round(Number(value) || 0));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function activityIcon(type) {
  if (type === 'quiz') return <FiCheckCircle size={15} />;
  if (type === 'session') return <FiClock size={15} />;
  if (type === 'roadmap_completed' || type === 'phase_completed') return <FiAward size={15} />;
  return <FiBookOpen size={15} />;
}

export default function HomePage() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState(null);
  const [dashboardActivity, setDashboardActivity] = useState({
    weekly_activity: [],
    weekly_totals: { minutes: 0, sessions: 0, quizzes: 0, activity_count: 0 },
    recent_activity: [],
  });
  const [reviewQueue, setReviewQueue] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activityLoading, setActivityLoading] = useState(true);

  useEffect(() => {
    let active = true;

    getDashboard()
      .then((res) => { if (active) setDashboard(res.data); })
      .catch(() => { if (active) setError('Could not load your dashboard. Is your backend running?'); })
      .finally(() => { if (active) setLoading(false); });

    getDashboardActivity()
      .then((res) => { if (active && res?.data) setDashboardActivity(res.data); })
      .catch(() => { /* Overview remains usable if the activity feed is unavailable. */ })
      .finally(() => { if (active) setActivityLoading(false); });

    getReviewQueue()
      .then((res) => { if (active) setReviewQueue(Array.isArray(res?.data) ? res.data : []); })
      .catch(() => { if (active) setReviewQueue([]); });

    getReminders()
      .then((res) => { if (active) setReminders(Array.isArray(res?.data) ? res.data : []); })
      .catch(() => { if (active) setReminders([]); });

    return () => { active = false; };
  }, []);

  if (loading) return <LoadingSpinner message="Loading your dashboard..." />;
  if (error || !dashboard) {
    return <div className="page"><div className="container"><div className="alert alert-error">{error || 'Could not load your dashboard.'}</div></div></div>;
  }

  const profile = dashboard.profile || {};
  const goals = Array.isArray(dashboard.goals) ? dashboard.goals : [];
  const skillsMastery = Array.isArray(dashboard.skills_mastery) ? dashboard.skills_mastery : [];
  const skillBuckets = dashboard.skill_buckets || { strong: [], needs_improvement: [], not_started: [] };
  const stats = dashboard.stats || {};
  const inProgress = [...goals]
    .filter((goal) => !goal.is_complete)
    .sort((a, b) => new Date(b.started_at || 0) - new Date(a.started_at || 0));
  const continueGoal = inProgress[0] || null;
  const progressPct = Math.max(0, Math.min(100, Number(continueGoal?.progress_pct) || 0));
  const weekly = Array.isArray(dashboardActivity.weekly_activity) ? dashboardActivity.weekly_activity : [];
  const weeklyTotals = dashboardActivity.weekly_totals || { minutes: 0, sessions: 0, quizzes: 0, activity_count: 0 };
  const recentActivity = Array.isArray(dashboardActivity.recent_activity) ? dashboardActivity.recent_activity.slice(0, 5) : [];
  const maxActivity = Math.max(1, ...weekly.map((day) => Number(day.activity_count) || 0));
  const dueReviews = [...reviewQueue].sort((a, b) => new Date(a.due_at || 0) - new Date(b.due_at || 0)).slice(0, 2);
  const openReminders = reminders
    .filter((reminder) => !reminder.completed)
    .sort((a, b) => new Date(a.due_at || 0) - new Date(b.due_at || 0));
  const nextReminder = openReminders[0] || null;

  return (
    <div className="page">
      <div className="home-dashboard-shell">
        <header className="home-dashboard-header">
          <div>
            <div className="home-card-kicker" style={{ marginBottom: 5 }}>{today()}</div>
            <h1>{greeting()}, {profile.username || 'learner'} 👋</h1>
            <p className="home-dashboard-subtitle">Your progress, priorities, and next steps—all in one place.</p>
          </div>
          <button className="btn btn-outline" onClick={() => navigate('/onboarding')}>
            <FiPlus size={15} /> New goal
          </button>
        </header>

        {/* Today's focus: the active path and a single clear next action. */}
        <section className="card home-focus-card">
          {continueGoal ? (
            <div className="home-focus-layout">
              <div>
                <div className="home-eyebrow"><FiTarget size={14} /> Today's focus</div>
                <h2 className="home-focus-title">Continue {continueGoal.goal_name}</h2>
                <p className="home-focus-detail">
                  {continueGoal.skills_completed || 0} of {continueGoal.skills_total || 0} skills completed. Keep working through your roadmap to build momentum.
                </p>
                <div className="home-focus-progress">
                  <div className="home-progress-track" role="progressbar" aria-label="Learning path progress" aria-valuenow={progressPct} aria-valuemin={0} aria-valuemax={100}>
                    <div className="home-progress-fill" style={{ width: `${progressPct}%` }} />
                  </div>
                  <span className="home-focus-percent">{progressPct}%</span>
                </div>
              </div>
              <button className="btn btn-primary" onClick={() => navigate(`/roadmap/${continueGoal.goal_id}`)}>
                Continue learning <FiArrowRight size={16} />
              </button>
            </div>
          ) : (
            <div className="home-focus-layout">
              <div>
                <div className="home-eyebrow"><FiTarget size={14} /> Your next step</div>
                <h2 className="home-focus-title">Set a learning goal to get started</h2>
                <p className="home-focus-detail">Create a personalized path and your dashboard will track progress, quizzes, and review tasks here.</p>
              </div>
              <button className="btn btn-primary" onClick={() => navigate('/onboarding')}>
                Start a learning goal <FiArrowRight size={16} />
              </button>
            </div>
          )}
        </section>

        <div className="home-dashboard-grid">
          <div className="home-primary-column">
            {/* Real activity, aggregated by the backend for the last seven days. */}
            <section className="card home-card">
              <div className="home-card-heading">
                <h3><span className="home-section-icon"><FiActivity size={16} /></span> Weekly learning activity</h3>
                <span className="home-card-kicker">Last 7 days</span>
              </div>
              <div className="home-chart-summary">
                <span className="home-chart-total">{formatMinutes(weeklyTotals.minutes)}</span>
                <span className="home-chart-total-label">study time logged</span>
              </div>
              {weekly.length > 0 ? (
                <div className="home-activity-chart" aria-label="Learning activity by day">
                  {weekly.map((day) => {
                    const count = Math.max(0, Number(day.activity_count) || 0);
                    const barHeight = count ? Math.max(8, (count / maxActivity) * 100) : 3;
                    return (
                      <div className="home-activity-day" key={day.date} title={`${day.label}: ${day.sessions || 0} sessions, ${day.quizzes || 0} quizzes, ${day.minutes || 0} minutes logged`}>
                        <div className="home-activity-bar-area">
                          <div className={`home-activity-bar${count ? ' is-active' : ''}`} style={{ height: `${barHeight}%` }} />
                        </div>
                        <span className="home-activity-day-label">{day.label}</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="home-empty-state">
                  <strong>Your weekly activity will appear here</strong>
                  <p>Quiz attempts and logged study sessions will build this chart as you learn.</p>
                </div>
              )}
              <div className="home-chart-legend">
                <span>{weeklyTotals.quizzes || 0} quizzes</span>
                <span>{weeklyTotals.sessions || 0} study sessions</span>
                <span>Bars show daily learning activity</span>
              </div>
              {!activityLoading && Number(weeklyTotals.activity_count || 0) === 0 && (
                <p className="home-card-kicker" style={{ marginTop: 12 }}>No activity recorded in the last seven days yet. Start a quiz or log a study session to begin your history.</p>
              )}
            </section>

            <section className="card home-card">
              <div className="home-card-heading">
                <h3><span className="home-section-icon"><FiTrendingUp size={16} /></span> Recent activity</h3>
              </div>
              {activityLoading ? (
                <p className="home-task-empty">Loading recent activity…</p>
              ) : recentActivity.length ? (
                <div className="home-recent-list">
                  {recentActivity.map((item) => (
                    <div className="home-recent-item" key={item.id}>
                      <span className="home-recent-icon">{activityIcon(item.type)}</span>
                      <div>
                        <h4>{item.title}</h4>
                        <p>{item.detail}{item.goal_name ? ` · ${item.goal_name}` : ''}</p>
                        {item.goal_id && (
                          <button className="home-inline-link" style={{ marginTop: 5 }} onClick={() => navigate(`/roadmap/${item.goal_id}`)}>
                            Open roadmap <FiChevronRight size={12} />
                          </button>
                        )}
                      </div>
                      <span className="home-recent-time">{dateLabel(item.created_at, false)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="home-empty-state">
                  <strong>No recent activity yet</strong>
                  <p>Your quiz results, study sessions, and completed learning paths will show up here.</p>
                  <button className="home-inline-link" onClick={() => navigate(continueGoal ? `/roadmap/${continueGoal.goal_id}` : '/onboarding')}>
                    {continueGoal ? 'Continue learning' : 'Create your first goal'} <FiChevronRight size={13} />
                  </button>
                </div>
              )}
            </section>

            <section className="card home-card">
              <div className="home-card-heading">
                <h3><span className="home-section-icon"><FiTarget size={16} /></span> Your skills</h3>
                <button className="home-inline-link" onClick={() => navigate('/my-skills')}>View all <FiChevronRight size={13} /></button>
              </div>
              {skillsMastery.length ? (
                <div className="home-skills-list">
                  {skillsMastery.slice(0, 5).map((skill) => {
                    const mastery = Math.max(0, Math.min(100, Number(skill.mastery_pct) || 0));
                    return (
                      <div className="home-skill-row" key={skill.skill_name}>
                        <span className="home-skill-name" title={skill.skill_name}>{skill.skill_name}</span>
                        <div className="home-skill-track"><div className="home-skill-fill" style={{ width: `${mastery}%` }} /></div>
                        <span className="home-skill-pct">{mastery}%</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="home-empty-state">
                  <strong>No skills tracked yet</strong>
                  <p>Start a learning path to track your skill development over time.</p>
                  <button className="home-inline-link" onClick={() => navigate('/onboarding')}>Start a learning goal <FiChevronRight size={13} /></button>
                </div>
              )}
              {(skillBuckets.needs_improvement?.length > 0 || skillBuckets.not_started?.length > 0) && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginTop: 17 }}>
                  {skillBuckets.needs_improvement?.length > 0 && (
                    <div style={{ padding: 12, borderRadius: 10, background: '#fbf1e2' }}>
                      <div style={{ color: '#9b6a24', fontWeight: 700, fontSize: '.74rem', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}><FiAlertCircle size={12} /> Needs improvement</div>
                      {skillBuckets.needs_improvement.slice(0, 3).map((name) => <div key={name} style={{ color: '#9b6a24', fontSize: '.73rem', marginTop: 3 }}>{name}</div>)}
                    </div>
                  )}
                  {skillBuckets.not_started?.length > 0 && (
                    <div style={{ padding: 12, borderRadius: 10, background: '#fdecea' }}>
                      <div style={{ color: '#b65442', fontWeight: 700, fontSize: '.74rem', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}><FiCircle size={12} /> Not started</div>
                      {skillBuckets.not_started.slice(0, 3).map((name) => <div key={name} style={{ color: '#b65442', fontSize: '.73rem', marginTop: 3 }}>{name}</div>)}
                    </div>
                  )}
                </div>
              )}
            </section>
          </div>

          <div className="home-side-column">
            <section className="card home-card">
              <div className="home-card-heading">
                <h3><span className="home-section-icon"><FiZap size={16} /></span> At a glance</h3>
              </div>
              <div className="home-stat-grid">
                <MiniStat icon={<FiZap />} value={stats.day_streak ?? 0} label={stats.longest_streak > stats.day_streak ? `Day streak (best ${stats.longest_streak})` : "Day streak"} color="#e0604f" bg="#fdecea" />
                <MiniStat icon={<FiClock />} value={`${stats.total_learning_time_hours ?? 0}h`} label="Learning time" color="#d9824c" bg="#fdf1e7" />
                <MiniStat icon={<FiCheckCircle />} value={stats.skills_mastered ?? 0} label="Skills mastered" color="#4d9e6e" bg="#eaf6ee" />
                <MiniStat icon={<FiAward />} value={stats.learning_paths_completed ?? 0} label="Paths completed" color="#b9822a" bg="#fbf1e2" />
              </div>
            </section>

            <section className="card home-card">
              <div className="home-card-heading">
                <h3><span className="home-section-icon"><FiCalendar size={16} /></span> Reviews & reminders</h3>
                <button className="home-inline-link" onClick={() => navigate('/study-planner')}>Study planner <FiChevronRight size={13} /></button>
              </div>

              <div className="home-task-section">
                <div className="home-task-section-heading">
                  <span>Due for review</span>
                  <span className="home-task-count">{reviewQueue.length}</span>
                </div>
                {dueReviews.length ? dueReviews.map((item) => (
                    <div className="home-task-item" key={item.id ?? `${item.goal_id}-${item.skill_name}`}>
                      <div>
                        <strong title={item.skill_name}>{item.skill_name}</strong>
                        <small>Due {dateLabel(item.due_at)}{item.last_score != null ? ` · Last score ${item.last_score}%` : ''}</small>
                      </div>
                      <button className="home-inline-link" onClick={() => navigate(`/roadmap/${item.goal_id}`)} aria-label={`Open roadmap for ${item.skill_name}`}>Open <FiChevronRight size={12} /></button>
                    </div>
                )) : <p className="home-task-empty">No skills are due for review right now.</p>}
              </div>

              <div className="home-task-section">
                <div className="home-task-section-heading">
                  <span>Next reminder</span>
                  {nextReminder && <span className="home-card-kicker">{dateLabel(nextReminder.due_at)}</span>}
                </div>
                {nextReminder ? (
                  <div className="home-task-item">
                    <div>
                      <strong title={nextReminder.title}>{nextReminder.title}</strong>
                      <small>{nextReminder.goal_id ? (goals.find((goal) => String(goal.goal_id) === String(nextReminder.goal_id))?.goal_name || 'Learning path') : 'General study reminder'}</small>
                    </div>
                    <button className="home-inline-link" onClick={() => navigate('/study-planner')}>View <FiChevronRight size={12} /></button>
                  </div>
                ) : <p className="home-task-empty">No open reminders. Add one to plan your next study session.</p>}
              </div>
            </section>

            <section className="card home-card">
              <div className="home-card-heading">
                <h3>Quick actions</h3>
              </div>
              <div className="home-quick-actions">
                <button className="btn btn-outline" style={{ justifyContent: 'flex-start' }} onClick={() => navigate('/onboarding')}><FiPlus size={15} /> New learning goal</button>
                <button className="btn btn-outline" style={{ justifyContent: 'flex-start' }} onClick={() => navigate('/saved-roadmaps')}><FiMap size={15} /> All learning paths</button>
                <button className="btn btn-outline" style={{ justifyContent: 'flex-start' }} onClick={() => navigate('/my-skills')}><FiStar size={15} /> My skills</button>
                <button className="btn btn-outline" style={{ justifyContent: 'flex-start' }} onClick={() => navigate('/my-reviews')}><FiMessageSquare size={15} /> My reviews</button>
              </div>
            </section>
          </div>
        </div>

        {dashboard.quote && (
          <footer className="home-quote">
            <FiBookOpen size={17} />
            <div><p>“{dashboard.quote}”</p><span>— LearnPath</span></div>
          </footer>
        )}
      </div>
    </div>
  );
}

function MiniStat({ icon, value, label, color, bg }) {
  return (
    <div className="home-stat-item" style={{ background: bg }}>
      <div className="home-stat-item-icon" style={{ color }}>{icon}</div>
      <div className="home-stat-item-value">{value}</div>
      <div className="home-stat-item-label">{label}</div>
    </div>
  );
}
