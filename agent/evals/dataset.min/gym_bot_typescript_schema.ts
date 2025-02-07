export interface Exercise {
    name: string;
    muscleGroup: string;
    sets: number;
    reps: number;
    weight: number;
    equipment: string[];
    timestamp: string; // ISO UTC datetime string
}

export interface RoutineRequest {
    duration: string; // ISO duration string
    equipment: string[];
    targetMuscles: string[];
}

export interface WorkoutRoutine {
    exercises: Exercise[];
    totalDuration: string; // ISO duration string
    difficulty: string;
}

export interface Progress {
    exercise: string;
    history: Exercise[];
    weightProgress: number;
    repsProgress: number;
}

export type GymTrackerFunctions = {
    recordExercise: (exercise: Exercise) => void;
    getProgress: (exerciseName: string, from: string, to: string) => Progress;
    suggestRoutine: (request: RoutineRequest) => WorkoutRoutine;
    updateAvailableEquipment: (equipment: string[]) => void;
}