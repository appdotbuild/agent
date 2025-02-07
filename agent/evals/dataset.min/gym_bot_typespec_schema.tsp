model Exercise {
    name: string;
    muscleGroup: string;
    sets: integer;
    reps: integer;
    weight: float;
    equipment: string[];
    timestamp: utcDateTime;
}

model RoutineRequest {
    duration: duration;
    equipment: string[];
    targetMuscles: string[];
}

model WorkoutRoutine {
    exercises: Exercise[];
    totalDuration: duration;
    difficulty: string;
}

model Progress {
    exercise: string;
    history: Exercise[];
    weightProgress: float;
    repsProgress: integer;
}

interface GymTracker {
    @llm_func(2)
    recordExercise(exercise: Exercise): void;

    @llm_func(1)
    getProgress(exerciseName: string, from: utcDateTime, to: utcDateTime): Progress;

    @llm_func(3)
    suggestRoutine(request: RoutineRequest): WorkoutRoutine;

    @llm_func(1)
    updateAvailableEquipment(equipment: string[]): void;
}