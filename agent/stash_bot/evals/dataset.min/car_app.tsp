model CarDetails {
    make: string,
    modelName: string,
    year: integer,
    type: string
  }
  
  model PoemStyle {
    styleType: string,
    length: integer,
    mood: string
  }
  
  model Poem {
    id: string,
    content: string,
    car: CarDetails,
    style: PoemStyle,
    createdAt: utcDateTime
  }
  
  interface CarPoetBot {
    @llm_func(2)
    generatePoem(car: CarDetails, style: PoemStyle): Poem;
    
    @llm_func(1)
    savePoem(poem: Poem): void;
    
    @llm_func(1)
    getFavoritePoems(fromDate: utcDateTime, toDate: utcDateTime): Poem[];
  }