import api from './axios';

export const sendChatMessage = (message, goalId) =>
  api.post('/chat', { message, goal_id: goalId || null });

export const getChatHistory = (goalId) =>
  api.get('/chat/history', { params: goalId ? { goal_id: goalId } : {} });
