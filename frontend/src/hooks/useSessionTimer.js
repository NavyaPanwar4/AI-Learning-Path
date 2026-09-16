import { useEffect, useRef } from 'react';
import { logSession } from '../api/user';

const MIN_LOGGABLE_MINUTES = 0.1; // ~6 seconds — filters out quick nav-throughs

/**
 * Tracks how long the user stays mounted on a learning page and logs it as
 * a real study session when they leave. Powers the real "Total Learning
 * Time" and contributes to "Day Streak" on the profile dashboard.
 */
export default function useSessionTimer() {
  const startRef = useRef(Date.now());

  useEffect(() => {
    startRef.current = Date.now();

    return () => {
      const minutes = (Date.now() - startRef.current) / 60000;
      if (minutes >= MIN_LOGGABLE_MINUTES) {
        logSession(minutes).catch(() => {});
      }
    };
  }, []);
}