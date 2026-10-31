import api from './axios';

export const sendChatMessage = (message, goalId) =>
  api.post('/chat', { message, goal_id: goalId || null });

export const explainQuizAnswer = (quizId, questionId, selectedIndex) =>
  api.post('/chat/explain-answer', { quiz_id: quizId, question_id: questionId, selected_index: selectedIndex });

export const getChatHistory = (goalId) =>
  api.get('/chat/history', { params: goalId ? { goal_id: goalId } : {} });

export const clearChatHistory = () => api.delete('/chat/history');

/** Stream tutor tokens over Server-Sent Events using the browser Fetch API. */
export async function sendChatMessageStream(message, onDelta, goalId, signal) {
  const token = sessionStorage.getItem('access_token');
  const headers = { 'Content-Type': 'application/json', Accept: 'text/event-stream' };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${api.defaults.baseURL || ''}/chat/stream`, {
    method: 'POST',
    credentials: 'include',
    headers,
    body: JSON.stringify({ message, goal_id: goalId || null }),
    signal,
  });

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem('authenticated');
      localStorage.removeItem('user');
      sessionStorage.removeItem('access_token');
      window.location.href = '/login';
    }
    let detail = `Tutor request failed (${response.status}).`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch { /* response might not be JSON */ }
    throw new Error(detail);
  }
  if (!response.body) throw new Error('Streaming is not supported by this browser.');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let goal = null;

  const dispatch = (block) => {
    const data = block.split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n');
    if (!data) return;
    const event = JSON.parse(data);
    if (event.type === 'delta' && event.content) onDelta?.(event.content);
    if (event.type === 'done') goal = event.goal_id ?? null;
    if (event.type === 'error') throw new Error(event.message || 'Tutor stream failed.');
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (block.trim()) dispatch(block);
      }
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
    return { goal_id: goal };
  } finally {
    reader.releaseLock();
  }
}
