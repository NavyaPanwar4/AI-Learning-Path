import { useContext } from 'react';
import { RoadmapGenerationContext } from './RoadmapGenerationContext.js';

export function useRoadmapGeneration() {
  const context = useContext(RoadmapGenerationContext);

  if (!context) {
    throw new Error(
      'useRoadmapGeneration must be used within RoadmapGenerationProvider.'
    );
  }

  return context;
}