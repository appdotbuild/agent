// {{typescript_schema_definitions}}
export interface PoemStyle {
    name: string;
    versesCount: number;
    linesPerVerse: number;
}

export interface CarPoem {
    title: string;
    content: string;
    style: PoemStyle;
    topic: string;
    createdAt: string;  // ISO format UTC datetime
}

export interface CarPoemBot {
    generateCarPoem(style: string, topic: string): Promise<CarPoem>;
    listAvailableStyles(): Promise<PoemStyle[]>;
}