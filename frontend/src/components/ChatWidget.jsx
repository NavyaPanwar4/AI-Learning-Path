import { useState, useEffect, useRef } from 'react';
import { FiMessageCircle, FiX, FiSend, FiCpu } from 'react-icons/fi';
import { sendChatMessage, getChatHistory } from '../api/chat';

// Tiny no-dependency renderer for the bit of markdown the tutor model
// actually produces: headings, **bold**, *italic*, `code`, lists, paragraphs.
function renderInline(text, keyPrefix) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).filter(Boolean);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('*') && part.endsWith('*')) {
      return <em key={`${keyPrefix}-${i}`}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={`${keyPrefix}-${i}`} style={{
          background: 'rgba(0,0,0,.06)', padding: '1px 5px', borderRadius: 4,
          fontSize: '.82em', fontFamily: 'ui-monospace, monospace',
        }}>
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={`${keyPrefix}-${i}`}>{part}</span>;
  });
}

const HEADING_RE = /^\s*#{1,6}\s+(.*)$/;

function ChatMessageContent({ content }) {
  const blocks = content.trim().split(/\n{2,}/);
  let blockKey = 0;
  const rendered = [];

  blocks.forEach((block) => {
    const rawLines = block.split('\n').filter((l) => l.trim() !== '');

    // Headings render as their own line even mid-block — split them out first.
    let runStart = 0;
    const flushParagraph = (lines) => {
      if (lines.length === 0) return;
      rendered.push(
        <p key={blockKey} style={{ margin: blockKey === 0 ? '0 0 8px' : '8px 0 0' }}>
          {lines.map((l, li) => (
            <span key={li}>
              {li > 0 && <br />}
              {renderInline(l, `${blockKey}-${li}`)}
            </span>
          ))}
        </p>
      );
      blockKey += 1;
    };

    const isBulletLine = (l) => /^\s*([-*•]|\d+[.)])\s+/.test(l);

    let i = 0;
    while (i < rawLines.length) {
      const line = rawLines[i];
      const heading = line.match(HEADING_RE);

      if (heading) {
        rendered.push(
          <p key={blockKey} style={{ margin: blockKey === 0 ? '0 0 6px' : '10px 0 6px', fontWeight: 700 }}>
            {renderInline(heading[1], `${blockKey}-h`)}
          </p>
        );
        blockKey += 1;
        i += 1;
        continue;
      }

      if (isBulletLine(line)) {
        const listLines = [];
        while (i < rawLines.length && isBulletLine(rawLines[i])) {
          listLines.push(rawLines[i]);
          i += 1;
        }
        const ordered = /^\s*\d+[.)]\s+/.test(listLines[0]);
        const ListTag = ordered ? 'ol' : 'ul';
        rendered.push(
          <ListTag key={blockKey} style={{ margin: blockKey === 0 ? '0 0 8px' : '8px 0', paddingLeft: 18 }}>
            {listLines.map((l, li) => (
              <li key={li} style={{ marginBottom: 3 }}>
                {renderInline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ''), `${blockKey}-${li}`)}
              </li>
            ))}
          </ListTag>
        );
        blockKey += 1;
        continue;
      }

      const paraLines = [];
      while (i < rawLines.length && !isBulletLine(rawLines[i]) && !HEADING_RE.test(rawLines[i])) {
        paraLines.push(rawLines[i]);
        i += 1;
      }
      flushParagraph(paraLines);
    }
  });

  return <>{rendered}</>;
}

export default function ChatWidget() {
  const token = localStorage.getItem('token');

  const [open, setOpen] = useState(false);
  const [loadedHistory, setLoadedHistory] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const bottomRef = useRef(null);

  useEffect(() => {
    if (open && !loadedHistory) {
      getChatHistory()
        .then((res) => setMessages(res.data || []))
        .catch(() => setError('Could not load your previous conversation.'))
        .finally(() => setLoadedHistory(true));
    }
  }, [open, loadedHistory]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending, open]);

  if (!token) return null;

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;

    setError('');
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setInput('');
    setSending(true);

    try {
      const res = await sendChatMessage(text);
      setMessages((prev) => [...prev, { role: 'assistant', content: res.data.reply }]);
    } catch {
      setError("Couldn't reach the tutor. Please try again.");
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? 'Close AI tutor' : 'Open AI tutor'}
        style={{
          position: 'fixed', right: 24, bottom: 24, zIndex: 1000,
          width: 56, height: 56, borderRadius: '50%', border: 'none', cursor: 'pointer',
          display: 'grid', placeItems: 'center', color: '#fff',
          background: 'var(--color-accent)', boxShadow: '0 8px 22px rgba(240,109,85,.4)',
        }}
      >
        {open ? <FiX size={22} /> : <FiMessageCircle size={22} />}
      </button>

      {open && (
        <div style={{
          position: 'fixed', right: 24, bottom: 92, zIndex: 1000,
          width: 360, maxWidth: 'calc(100vw - 32px)', height: 500, maxHeight: 'calc(100vh - 140px)',
          display: 'flex', flexDirection: 'column',
          background: 'var(--color-surface)', border: '1px solid var(--color-border)',
          borderRadius: 16, boxShadow: '0 20px 50px rgba(35,37,39,.2)', overflow: 'hidden',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px',
            background: 'var(--color-primary)', color: '#fff',
          }}>
            <div style={{
              width: 30, height: 30, borderRadius: 9, display: 'grid', placeItems: 'center',
              background: 'rgba(255,255,255,.15)',
            }}>
              <FiCpu size={16} />
            </div>
            <div>
              <div style={{ fontSize: '.86rem', fontWeight: 700 }}>AI Tutor</div>
              <div style={{ fontSize: '.68rem', opacity: .75 }}>Knows your goal &amp; progress</div>
            </div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: '14px 14px 6px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            {messages.length === 0 && (
              <div style={{ color: 'var(--color-text-muted)', fontSize: '.82rem', textAlign: 'center', marginTop: 30, padding: '0 10px' }}>
                Ask me anything about your current phase, a concept you're stuck on, or say "what should I learn next?"
              </div>
            )}
            {messages.map((m, i) => (
              <div
                key={i}
                style={{
                  alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '85%', padding: '9px 12px', borderRadius: 12,
                  fontSize: '.85rem', lineHeight: 1.5,
                  background: m.role === 'user' ? 'var(--color-accent)' : '#f1f0eb',
                  color: m.role === 'user' ? '#fff' : 'var(--color-text)',
                  borderBottomRightRadius: m.role === 'user' ? 2 : 12,
                  borderBottomLeftRadius: m.role === 'user' ? 12 : 2,
                }}
              >
                {m.role === 'assistant' ? <ChatMessageContent content={m.content} /> : m.content}
              </div>
            ))}
            {sending && (
              <div style={{ alignSelf: 'flex-start', padding: '9px 12px', borderRadius: 12, background: '#f1f0eb', fontSize: '.85rem', color: 'var(--color-text-muted)' }}>
                Thinking…
              </div>
            )}
            {error && <div style={{ color: '#c0574a', fontSize: '.78rem', textAlign: 'center' }}>{error}</div>}
            <div ref={bottomRef} />
          </div>

          <div style={{ display: 'flex', gap: 8, padding: 12, borderTop: '1px solid var(--color-border)' }}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask your tutor..."
              rows={1}
              style={{
                flex: 1, resize: 'none', border: '1px solid var(--color-border)', borderRadius: 10,
                padding: '9px 11px', fontSize: '.85rem', fontFamily: 'inherit', outline: 'none',
              }}
            />
            <button
              className="btn btn-primary"
              onClick={handleSend}
              disabled={sending || !input.trim()}
              style={{ minHeight: 'auto', padding: '0 14px', opacity: sending || !input.trim() ? .6 : 1 }}
            >
              <FiSend size={15} />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
