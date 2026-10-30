import { useEffect, useRef } from 'react';
import { logSession } from '../api/user';

const MIN_LOGGABLE_MINUTES = 0.1; // ~6 seconds — filters out quick nav-throughs

/**
 * Tracks how long the user stays mounted on a learning page and logs it as
 * a real study session when they leave. Powers the real "Total Learning
 * Time" and contributes to "Day Streak" on the profile dashboard.
 */
export default function useSessionTimer() {
  const startRef = useRef(null);
  const accumulatedRef = useRef(0);

  useEffect(() => {
    const start = () => {
      if (document.visibilityState === 'visible' && startRef.current === null) startRef.current = Date.now();
    };
    const pause = () => {
      if (startRef.current !== null) {
        accumulatedRef.current += Date.now() - startRef.current;
        startRef.current = null;
      }
    };
    start();
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') start();
      else pause();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      pause();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      const minutes = accumulatedRef.current / 60000;
      if (minutes >= MIN_LOGGABLE_MINUTES) {
        logSession(minutes).catch(() => {});
      }
    };
  }, []);
}