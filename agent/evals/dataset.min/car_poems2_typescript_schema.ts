// This is a TypeScript schema for the car_poems2 application.


export interface CarPoem2Bot {
  generateCarPoemOrNot2(options: { style: string | null, topic: string | null }): Promise<string | null>;
  listAvailableStylesIncludingNone(): Promise<string[]>;
}