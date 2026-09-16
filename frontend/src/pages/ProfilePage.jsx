import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FiEdit2, FiMail, FiBookOpen, FiBarChart2, FiGlobe, FiCalendar, FiTarget,
  FiPlus, FiClock, FiCheckCircle, FiStar, FiZap, FiAward, FiTrendingUp,
  FiHelpCircle, FiCode, FiCpu, FiAlertCircle, FiCircle, FiClipboard,
} from 'react-icons/fi';
import { getDashboard, getGoals, updateProfile, updatePersonalInfo, changePassword } from '../api/user';
import LoadingSpinner from '../components/LoadingSpinner';

const EXPERIENCE_OPTS = ['beginner', 'intermediate', 'advanced'];
const STYLE_OPTS = ['visual', 'reading', 'interactive'];
const PACE_OPTS = ['Slow', 'Normal', 'Fast'];
const SESSION_OPTS = ['15-30 min', '30-60 min', '60-90 min', '90+ min'];

function goalIcon(goalName = '') {
  const n = goalName.toLowerCase();
  if (n.includes('data') || n.includes('analyst') || n.includes('ml') || n.includes('machine learning')) return <FiBarChart2 size={20} />;
  if (n.includes('react') || n.includes('frontend') || n.includes('web') || n.includes('developer')) return <FiCode size={20} />;
  return <FiTarget size={20} />;
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
}

function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((s) => s[0].toUpperCase()).join('') || '?';
}

export default function ProfilePage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [dashboard, setDashboard] = useState(null);
  const [goalsList, setGoalsList] = useState([]);

  const [editingProfile, setEditingProfile] = useState(false);
  const [editingPrefs, setEditingPrefs] = useState(false);

  const [profileForm, setProfileForm] = useState({ bio: '', title: '', education: '', language: 'English', avatar_url: '' });
  const [prefsForm, setPrefsForm] = useState({
    goal_id: '', experience_level: 'beginner', available_hours_per_week: 10, learning_style: 'visual',
    session_length: '30-60 min', preferred_content: 'Videos, Docs', learning_pace: 'Normal', preferred_difficulty: '',
  });
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [formError, setFormError] = useState('');

  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [pwSaving, setPwSaving] = useState(false);
  const [pwError, setPwError] = useState('');
  const [pwSuccess, setPwSuccess] = useState('');

  const loadDashboard = () => {
    return Promise.all([getDashboard(), getGoals()])
      .then(([dashRes, goalsRes]) => {
        setDashboard(dashRes.data);
        setGoalsList(goalsRes.data);
        const p = dashRes.data.profile;
        const prefs = dashRes.data.preferences;
        setProfileForm({ bio: p.bio || '', title: p.title || '', education: p.education || '', language: p.language || 'English', avatar_url: p.avatar_url || '' });
        setPrefsForm({
          goal_id: prefs.goal_id ? String(prefs.goal_id) : '',
          experience_level: prefs.experience_level || 'beginner',
          available_hours_per_week: prefs.available_hours_per_week || 10,
          learning_style: prefs.learning_style || 'visual',
          session_length: prefs.session_length || '30-60 min',
          preferred_content: prefs.preferred_content || 'Videos, Docs',
          learning_pace: prefs.learning_pace || 'Normal',
          preferred_difficulty: prefs.preferred_difficulty || '',
        });
      });
  };

  useEffect(() => {
    loadDashboard()
      .catch(() => setLoadError('Failed to load your profile.'))
      .finally(() => setLoading(false));
  }, []);

  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setFormError('');
    setSavingProfile(true);
    try {
      await updatePersonalInfo(profileForm);
      await loadDashboard();
      setEditingProfile(false);
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Failed to update profile.');
    } finally {
      setSavingProfile(false);
    }
  };

  const handleSavePrefs = async (e) => {
    e.preventDefault();
    setFormError('');
    if (!prefsForm.goal_id) {
      setFormError('Please select a learning goal.');
      return;
    }
    setSavingPrefs(true);
    try {
      await updateProfile({ ...prefsForm, available_hours_per_week: Number(prefsForm.available_hours_per_week) });
      await loadDashboard();
      setEditingPrefs(false);
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Failed to update preferences.');
    } finally {
      setSavingPrefs(false);
    }
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    setPwError('');
    setPwSuccess('');
    if (newPassword.length < 8 || !/[A-Z]/.test(newPassword) || !/[0-9]/.test(newPassword)) {
      setPwError('New password must be at least 8 characters and include one uppercase letter and one number.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setPwError('New passwords do not match.');
      return;
    }
    setPwSaving(true);
    try {
      await changePassword(oldPassword, newPassword);
      setPwSuccess('Password updated.');
      setOldPassword(''); setNewPassword(''); setConfirmPassword('');
    } catch (err) {
      const msg = err.response?.data?.detail;
      setPwError(Array.isArray(msg) ? msg.map((m) => m.msg).join(', ') : msg || 'Failed to update password.');
    } finally {
      setPwSaving(false);
    }
  };

  if (loading) return <LoadingSpinner message="Loading your profile..." />;
  if (loadError) return <div className="page"><div className="container"><div className="alert alert-error">{loadError}</div></div></div>;

  const { profile, preferences, goals, skills_mastery, skill_buckets, ai_summary, quote, stats } = dashboard;

  return (
    <div className="page">
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ fontSize: '2rem', marginBottom: 6 }}>My Profile</h1>
            <p style={{ color: 'var(--color-text-muted)' }}>Manage your profile, goals, skills and learning preferences.</p>
          </div>
          <button className="btn btn-outline" onClick={() => setEditingProfile((v) => !v)}>
            <FiEdit2 size={14} /> {editingProfile ? 'Cancel' : 'Edit Profile'}
          </button>
        </div>

        {formError && <div className="alert alert-error" style={{ marginBottom: 20 }}>{formError}</div>}

        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 24, alignItems: 'start' }}>
          <div style={{ display: 'grid', gap: 24 }}>

            <div className="card">
              {!editingProfile ? (
                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                  <div style={{
                    width: 88, height: 88, borderRadius: '50%', flexShrink: 0, overflow: 'hidden',
                    background: profile.avatar_url ? `url(${profile.avatar_url}) center/cover` : 'var(--color-accent-soft)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.6rem', fontWeight: 700, color: 'var(--color-primary)',
                  }}>
                    {!profile.avatar_url && initials(profile.username)}
                  </div>
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <h2 style={{ fontSize: '1.3rem', marginBottom: 2 }}>{profile.username}</h2>
                    {profile.title && <div style={{ color: 'var(--color-text-muted)', marginBottom: 8 }}>{profile.title}</div>}
                    {profile.bio && <p style={{ color: '#5d5f5a', fontSize: '.9rem', maxWidth: 420 }}>{profile.bio}</p>}
                  </div>
                  <div style={{ display: 'grid', gap: 10, minWidth: 190, fontSize: '.86rem', color: '#5d5f5a' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FiMail size={14} /> {profile.email}</span>
                    {profile.education && <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FiBookOpen size={14} /> {profile.education}</span>}
                    {preferences.experience_level && (
                      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <FiBarChart2 size={14} /> {preferences.experience_level.charAt(0).toUpperCase() + preferences.experience_level.slice(1)}
                      </span>
                    )}
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FiGlobe size={14} /> {profile.language}</span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FiCalendar size={14} /> Joined {formatDate(profile.joined_date)}</span>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleSaveProfile}>
                  <h3 style={{ marginBottom: 16 }}>Edit Profile</h3>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 16 }}>
                    <div className="input-group">
                      <label>Title</label>
                      <input type="text" placeholder="e.g. Engineering Student" value={profileForm.title} onChange={(e) => setProfileForm({ ...profileForm, title: e.target.value })} />
                    </div>
                    <div className="input-group">
                      <label>Education</label>
                      <input type="text" placeholder="e.g. B.Tech, MAIT" value={profileForm.education} onChange={(e) => setProfileForm({ ...profileForm, education: e.target.value })} />
                    </div>
                    <div className="input-group">
                      <label>Language</label>
                      <input type="text" value={profileForm.language} onChange={(e) => setProfileForm({ ...profileForm, language: e.target.value })} />
                    </div>
                    <div className="input-group">
                      <label>Avatar URL</label>
                      <input type="text" placeholder="https://..." value={profileForm.avatar_url} onChange={(e) => setProfileForm({ ...profileForm, avatar_url: e.target.value })} />
                    </div>
                  </div>
                  <div className="input-group" style={{ marginBottom: 20 }}>
                    <label>Bio</label>
                    <textarea value={profileForm.bio} onChange={(e) => setProfileForm({ ...profileForm, bio: e.target.value })} placeholder="A short line about yourself" />
                  </div>
                  <button className="btn btn-primary" type="submit" disabled={savingProfile}>{savingProfile ? 'Saving...' : 'Save Changes'}</button>
                </form>
              )}
            </div>

            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
                <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FiTarget color="var(--color-accent)" /> Current Learning Goals</h3>
                <button className="btn btn-outline" style={{ minHeight: 34, padding: '6px 12px', fontSize: '.8rem' }} onClick={() => navigate('/onboarding')}>
                  <FiPlus size={14} /> Add Goal
                </button>
              </div>

              {goals.length === 0 ? (
                <p style={{ color: 'var(--color-text-muted)', fontSize: '.88rem' }}>No learning paths yet — add a goal to get started.</p>
              ) : (
                <div style={{ display: 'grid', gap: 14 }}>
                  {goals.map((g) => (
                    <div key={g.goal_id} style={{ border: '1px solid var(--color-border)', borderRadius: 12, padding: 16, background: '#fcfbf8' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 10 }}>
                        <div style={{ display: 'flex', gap: 12 }}>
                          <div style={{ width: 40, height: 40, borderRadius: 10, background: 'var(--color-accent-soft)', color: 'var(--color-accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                            {goalIcon(g.goal_name)}
                          </div>
                          <div>
                            <div style={{ fontWeight: 700 }}>{g.goal_name}</div>
                            <div style={{ color: 'var(--color-text-muted)', fontSize: '.78rem' }}>
                              {g.is_complete ? 'Completed' : `${g.skills_completed} / ${g.skills_total} skills completed`}
                            </div>
                          </div>
                        </div>
                        <button className="btn btn-outline" style={{ minHeight: 32, padding: '5px 12px', fontSize: '.78rem', whiteSpace: 'nowrap' }} onClick={() => navigate(`/roadmap/${g.goal_id}`)}>
                          View Path
                        </button>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 6, alignItems: 'center', marginBottom: 8 }}>
                        <div style={{ height: 6, borderRadius: 999, background: '#e7e6df', overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${g.progress_pct}%`, background: 'var(--color-accent)', borderRadius: 'inherit' }} />
                        </div>
                        <span style={{ fontSize: '.78rem', fontWeight: 700, color: 'var(--color-text-muted)' }}>{g.progress_pct}%</span>
                      </div>
                      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: '.76rem', color: 'var(--color-text-muted)' }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}><FiCalendar size={12} /> Started: {formatDate(g.started_at)}</span>
                        {!g.is_complete && <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}><FiCalendar size={12} /> Est. completion: {formatDate(g.estimated_completion)}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
                <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FiBarChart2 color="var(--color-accent)" /> Learning Statistics</h3>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
                <StatTile icon={<FiClock />} value={`${stats.total_learning_time_hours}h`} label="Total Learning Time" color="#f0a06d" bg="#fdf1e7" />
                <StatTile icon={<FiCheckCircle />} value={stats.topics_completed} label="Topics Completed" color="#4d9e6e" bg="#eaf6ee" />
                                <StatTile icon={<FiStar />} value={stats.average_quiz_score !== null ? `${stats.average_quiz_score}%` : '—'} label="Average Quiz Score" color="#4a7fd6" bg="#eaf1fc" />
                <StatTile icon={<FiZap />} value={stats.day_streak} label="Day Streak" color="#e0604f" bg="#fdecea" />
                <StatTile icon={<FiBookOpen />} value={stats.skills_in_progress} label="Skills in Progress" color="#6a5ccf" bg="#efecfb" />
                <StatTile icon={<FiAward />} value={stats.skills_mastered} label="Skills Mastered" color="#c7862f" bg="#fbf1e2" />
                <StatTile icon={<FiTrendingUp />} value={stats.learning_paths_completed} label="Learning Paths Completed" color="#4d9e6e" bg="#eaf6ee" />
                <StatTile icon={<FiHelpCircle />} value={stats.practice_questions_solved} label="Practice Questions Solved" color="#4a7fd6" bg="#eaf1fc" />
              </div>
              <p style={{ marginTop: 14, fontSize: '.72rem', color: 'var(--color-text-muted)' }}>
                                All numbers here reflect your real activity — session time, quiz attempts, completed phases and roadmaps. Take a practice quiz or spend time on a roadmap to see them move.
              </p>
            </div>
          </div>

          <div style={{ display: 'grid', gap: 24 }}>

            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
                <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FiTarget color="var(--color-accent)" /> Learning Preferences</h3>
                <button className="btn btn-outline" style={{ minHeight: 32, padding: '5px 12px', fontSize: '.78rem' }} onClick={() => setEditingPrefs((v) => !v)}>
                  {editingPrefs ? 'Cancel' : 'Edit'}
                </button>
              </div>

              {!editingPrefs ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 16 }}>
                  <PrefItem icon={<FiClock />} label="Weekly Time Budget" value={`${preferences.available_hours_per_week} hours/week`} />
                  <PrefItem icon={<FiClock />} label="Session Length" value={preferences.session_length || '—'} />
                  <PrefItem icon={<FiClipboard />} label="Preferred Content" value={preferences.preferred_content || '—'} />
                  <PrefItem icon={<FiTrendingUp />} label="Learning Pace" value={preferences.learning_pace || '—'} />
                  <PrefItem icon={<FiBarChart2 />} label="Preferred Difficulty" value={preferences.preferred_difficulty || preferences.experience_level || '—'} />
                  <PrefItem icon={<FiBookOpen />} label="Learning Style" value={preferences.learning_style || '—'} />
                </div>
              ) : (
                <form onSubmit={handleSavePrefs} style={{ display: 'grid', gap: 16 }}>
                  <div className="input-group">
                    <label>Current Goal</label>
                    <select value={prefsForm.goal_id} onChange={(e) => setPrefsForm({ ...prefsForm, goal_id: e.target.value })}>
                      <option value="">Select a goal</option>
                      {goalsList.map((g) => <option key={g.goal_id} value={g.goal_id}>{g.goal_name}</option>)}
                    </select>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 14 }}>
                    <div className="input-group">
                      <label>Experience</label>
                      <select value={prefsForm.experience_level} onChange={(e) => setPrefsForm({ ...prefsForm, experience_level: e.target.value })}>
                        {EXPERIENCE_OPTS.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Hours/Week</label>
                      <input type="number" min={5} max={80} value={prefsForm.available_hours_per_week} onChange={(e) => setPrefsForm({ ...prefsForm, available_hours_per_week: e.target.value })} />
                    </div>
                    <div className="input-group">
                      <label>Learning Style</label>
                      <select value={prefsForm.learning_style} onChange={(e) => setPrefsForm({ ...prefsForm, learning_style: e.target.value })}>
                        {STYLE_OPTS.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Session Length</label>
                      <select value={prefsForm.session_length} onChange={(e) => setPrefsForm({ ...prefsForm, session_length: e.target.value })}>
                        {SESSION_OPTS.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Learning Pace</label>
                      <select value={prefsForm.learning_pace} onChange={(e) => setPrefsForm({ ...prefsForm, learning_pace: e.target.value })}>
                        {PACE_OPTS.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Preferred Content</label>
                      <input type="text" value={prefsForm.preferred_content} onChange={(e) => setPrefsForm({ ...prefsForm, preferred_content: e.target.value })} placeholder="Videos, Docs, Articles" />
                    </div>
                  </div>
                  <button className="btn btn-primary" type="submit" disabled={savingPrefs} style={{ justifySelf: 'start' }}>
                    {savingPrefs ? 'Saving...' : 'Save Preferences'}
                  </button>
                </form>
              )}
            </div>

            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
                <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FiBarChart2 color="var(--color-accent)" /> Skills & Mastery</h3>
                <button className="btn btn-ghost" style={{ minHeight: 'auto', padding: 0, fontSize: '.8rem', color: 'var(--color-accent)' }} onClick={() => navigate('/my-skills')}>
                  View All
                </button>
              </div>

              {skills_mastery.length === 0 ? (
                <p style={{ color: 'var(--color-text-muted)', fontSize: '.88rem' }}>No skills recorded yet.</p>
              ) : (
                <div style={{ display: 'grid', gap: 10, marginBottom: 18 }}>
                  {skills_mastery.slice(0, 6).map((s) => (
                    <div key={s.skill_name} style={{ display: 'grid', gridTemplateColumns: '110px 1fr 40px', gap: 10, alignItems: 'center' }}>
                      <span style={{ fontSize: '.82rem', fontWeight: 600 }}>{s.skill_name}</span>
                      <div style={{ height: 7, borderRadius: 999, background: '#e7e6df', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${s.mastery_pct}%`, borderRadius: 'inherit', background: s.mastery_pct >= 70 ? '#e0604f' : s.mastery_pct >= 40 ? '#eda83d' : '#e0604f' }} />
                      </div>
                      <span style={{ fontSize: '.78rem', color: 'var(--color-text-muted)', textAlign: 'right' }}>{s.mastery_pct}%</span>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
                <BucketBox title="Strong Skills" color="#4d9e6e" bg="#eaf6ee" icon={<FiCheckCircle size={13} />} items={skill_buckets.strong} />
                <BucketBox title="Needs Improvement" color="#c7862f" bg="#fbf1e2" icon={<FiAlertCircle size={13} />} items={skill_buckets.needs_improvement} />
                <BucketBox title="Not Started" color="#c0574a" bg="#fdecea" icon={<FiCircle size={13} />} items={skill_buckets.not_started} />
              </div>
            </div>

            <div className="card">
              <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}><FiCpu color="var(--color-accent)" /> AI Learning Profile</h3>
              <p style={{ color: '#5d5f5a', fontSize: '.88rem', lineHeight: 1.6, marginBottom: 16 }}>{ai_summary}</p>
              <div style={{ padding: 14, borderRadius: 10, background: 'var(--color-accent-soft)' }}>
                <p style={{ fontStyle: 'italic', color: '#a65241', fontSize: '.88rem', marginBottom: 4 }}>"{quote}"</p>
                <span style={{ fontSize: '.75rem', color: '#a65241', fontWeight: 700 }}>— LearnPath AI</span>
              </div>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 24 }}>
          <h3 style={{ marginBottom: 16 }}>Change Password</h3>
          <form onSubmit={handleChangePassword} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, alignItems: 'end' }}>
            <div className="input-group">
              <label>Current Password</label>
              <input type="password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} required autoComplete="current-password" />
            </div>
            <div className="input-group">
              <label>New Password</label>
              <input type="password" placeholder="Min 8 chars, 1 uppercase, 1 number" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required autoComplete="new-password" />
            </div>
            <div className="input-group">
              <label>Confirm New Password</label>
              <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required autoComplete="new-password" />
            </div>
            <button className="btn btn-primary" type="submit" disabled={pwSaving}>{pwSaving ? 'Updating...' : 'Update Password'}</button>
          </form>
          {pwError && <div className="alert alert-error" style={{ marginTop: 14 }}>{pwError}</div>}
          {pwSuccess && <div className="alert alert-success" style={{ marginTop: 14 }}>{pwSuccess}</div>}
        </div>
      </div>
    </div>
  );
}

function StatTile({ icon, value, label, color, bg }) {
  return (
    <div style={{ padding: 14, borderRadius: 12, background: bg }}>
      <div style={{ color, marginBottom: 8 }}>{icon}</div>
      <div style={{ fontSize: '1.3rem', fontWeight: 800, color: '#333' }}>{value}</div>
      <div style={{ fontSize: '.74rem', color: 'var(--color-text-muted)' }}>{label}</div>
    </div>
  );
}

function PrefItem({ icon, label, value }) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--color-text-muted)', fontSize: '.72rem', marginBottom: 6 }}>
        {icon} {label}
      </div>
      <div style={{ fontWeight: 700, fontSize: '.9rem', textTransform: 'capitalize' }}>{value}</div>
    </div>
  );
}

function BucketBox({ title, color, bg, icon, items }) {
  return (
    <div style={{ padding: 12, borderRadius: 10, background: bg }}>
      <div style={{ color, fontWeight: 700, fontSize: '.78rem', marginBottom: 8 }}>{title}</div>
      {items.length === 0 ? (
        <div style={{ color, fontSize: '.76rem', opacity: 0.7 }}>None</div>
      ) : (
        <div style={{ display: 'grid', gap: 5 }}>
          {items.map((name) => (
            <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 6, color, fontSize: '.78rem' }}>
              {icon} {name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}