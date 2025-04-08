export interface CarDetails {
    make: string;
    modelName: string;
    year: number;
    type: string;
}

export interface PoemStyle {
    styleType: string;
    length: number;
    mood: string;
}

export interface Poem {
    id: string;
    content: string;
    car: CarDetails;
    style: PoemStyle;
    createdAt: Date;
}