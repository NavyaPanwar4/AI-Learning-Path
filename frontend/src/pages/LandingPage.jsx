import { Link, useNavigate } from 'react-router-dom';
import { FiArrowRight, FiBookOpen, FiCheck, FiCompass, FiFileText, FiMap, FiZap } from 'react-icons/fi';
import { useAuth } from '../context/useAuth';

const highlights = [
  ['Set the direction', 'Choose a goal, your experience, and the time you can realistically commit.'],
  ['See the whole path', 'Get a focused roadmap with skills, projects, and trusted learning resources.'],
  ['Study with momentum', 'Turn every phase into notes, practice prompts, and a clear next step.'],
];

export default function LandingPage() {
  const navigate = useNavigate();
  const { authenticated: isSignedIn } = useAuth();
  const primaryDestination = isSignedIn ? '/home' : '/register';

  return (
    <main className="landing-page">
      <nav className="landing-nav" aria-label="Public navigation">
        <Link to="/" className="landing-brand">
          <span><FiCompass size={18} /></span>
          Traject
        </Link>
        {!isSignedIn && (
          <div className="landing-nav-actions">
            <Link className="landing-login" to="/login">Log in</Link>
            <Link className="landing-login" to="/register">Register</Link>
          </div>
        )}
      </nav>

      <section className="landing-hero">
        <div className="landing-copy">
          <span className="landing-eyebrow"><FiZap size={14} /> A calmer way to grow</span>
          <h1>Build a learning path that feels <em>made for you.</em></h1>
          <p>Traject turns your goals, available time, and current skills into a focused plan you can actually follow.</p>
          <div className="landing-cta-row">
            <button className="btn btn-primary landing-main-cta" onClick={() => navigate(primaryDestination)}>
              {isSignedIn ? 'Go to Overview' : 'Create my account'} <FiArrowRight size={17} />
            </button>
            <span>{isSignedIn ? 'Your learning workspace is ready.' : 'Already have an account? Log in above.'}</span>
          </div>
          <div className="landing-proof"><span><FiCheck size={14} /></span>Personalized roadmap <span><FiCheck size={14} /></span>AI study notes <span><FiCheck size={14} /></span>Progress tracking</div>
        </div>

        <div className="landing-preview" aria-label="Example learning path preview">
          <div className="preview-topline"><span>YOUR TRAJECT ROADMAP</span><span className="preview-live">On track</span></div>
          <h2>Machine Learning foundations</h2>
          <p>9 weeks · 3 phases · tailored for 6 hours/week</p>
          <div className="preview-progress"><span>Progress</span><b>24%</b><i><em /></i></div>
          <div className="preview-step preview-step-current">
            <span className="preview-number">01</span><div><small>NOW LEARNING</small><strong>Python for data work</strong><p>Variables, functions, and data structures</p></div><FiArrowRight size={16} />
          </div>
          <div className="preview-step"><span className="preview-number">02</span><div><small>UP NEXT</small><strong>Core machine learning</strong></div></div>
          <div className="preview-step"><span className="preview-number">03</span><div><small>THEN</small><strong>Build your first model</strong></div></div>
          <div className="preview-note"><FiFileText size={16} /><span><b>AI study notes are ready</b><small>Review concepts and practice prompts</small></span><FiArrowRight size={15} /></div>
        </div>
      </section>

      <section className="landing-how">
        <div className="landing-section-intro"><span>DESIGNED FOR FOLLOW-THROUGH</span><h2>A clear plan, from your first step to your next milestone.</h2></div>
        <div className="landing-feature-grid">
          {highlights.map(([title, description], index) => (
            <article key={title} className="landing-feature"><span>0{index + 1}</span><h3>{title}</h3><p>{description}</p></article>
          ))}
        </div>
      </section>

      <section className="landing-tools">
        <div><span className="landing-eyebrow"><FiBookOpen size={14} /> Everything in one place</span><h2>Move from “I should learn this” to “I know what to do next.”</h2></div>
        <div className="landing-tool-list"><p><FiMap size={17} />Structured phases and projects</p><p><FiFileText size={17} />On-demand AI study guides</p><p><FiZap size={17} />Resources matched to your goal</p></div>
      </section>

      <footer className="landing-footer"><span>© {new Date().getFullYear()} Traject</span><Link to={isSignedIn ? '/home' : '/register'}>{isSignedIn ? 'Open Overview' : 'Start your path'} <FiArrowRight size={14} /></Link></footer>
    </main>
  );
}
